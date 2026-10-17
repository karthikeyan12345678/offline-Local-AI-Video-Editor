import json

import pytest
from fastapi.testclient import TestClient

from fakeserver import Fake, png_bytes
from ltxps.app import create_app
from ltxps.assistant.service import build_assistant_state
from ltxps.assistant import llm

TOKEN = "tok"
RESUME = (b"Asha K\nChennai, India | asha@example.com | +91 98765 43210\nExperience\nProgram Manager Jan 2021 - Present\n"
          b"- Led a team of 10 and cut cycle time by 30%\n- Built AWS and Kubernetes platform for 40k users\nEducation\nB.E. 2017\nSkills\nPython, AWS, Kubernetes, Agile\n"
          + b"filler words to reach a sensible length " * 20)


@pytest.fixture()
def fake():
    f = Fake()
    yield f
    f.close()


@pytest.fixture()
def client(tmp_path, fake):
    a = build_assistant_state(tmp_path / "assistant", TOKEN)
    a.settings.update({"provider": "custom", "providers": {"custom": {"base_url": fake.url + "/v1", "model": "m-one", "api_key": "sk-secret-1234"}},
                       "image": {"provider": "openai", "openai": {"base_url": fake.url + "/v1", "model": "img", "api_key": "k"}}})
    with TestClient(create_app(None, None, a), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        c.a, c.fake = a, fake
        yield c


def events(resp):
    out, ev = [], None
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            out.append((ev, json.loads(line[5:])))
    return out


def chat(client, text, files=(), options=None):
    cid = client.post("/api/assistant/conversations").json()["id"]
    r = client.post("/api/assistant/chat", json={"conversation_id": cid, "text": text, "file_ids": list(files), "options": options or {}})
    assert r.status_code == 200
    return cid, events(r)


def upload(client, name, data):
    r = client.post("/api/assistant/files", files={"file": (name, data)})
    assert r.status_code == 200, r.text
    return r.json()


def test_requires_token(tmp_path, fake):
    a = build_assistant_state(tmp_path / "x", TOKEN)
    with TestClient(create_app(None, None, a)) as c:
        assert c.get("/api/assistant/info").status_code == 401
        assert c.get("/api/assistant/info", params={"t": TOKEN}).status_code == 200
        assert c.get("/api/health", params={"t": TOKEN}).json()["product"] == "assistant"


def test_plain_chat_streams_and_persists(client):
    client.fake.reply = "Hello from the fake model."
    cid, ev = chat(client, "hi there")
    text = "".join(d["text"] for e, d in ev if e == "delta")
    assert text == "Hello from the fake model." and ev[-1][0] == "done"
    msgs = client.get(f"/api/assistant/conversations/{cid}").json()
    assert [m["role"] for m in msgs["messages"]] == ["user", "assistant"] and msgs["title"] == "hi there"


def test_anthropic_style_and_masked_keys(client):
    client.a.settings.update({"provider": "fcc", "providers": {"fcc": {"base_url": client.fake.url, "model": "x", "api_key": "tok-abcdef123"}}})
    client.fake.reply = "claude style reply"
    _, ev = chat(client, "hello")
    assert "".join(d["text"] for e, d in ev if e == "delta") == "claude style reply"
    path, headers, body = client.fake.requests[-1]
    assert path == "/v1/messages" and body["messages"][0]["role"] == "user" and headers.get("x-api-key") == "tok-abcdef123"
    pub = json.dumps(client.get("/api/assistant/settings").json(), ensure_ascii=False)
    assert "abcdef123" not in pub and "sk-secret-1234" not in pub and "••••" in pub
    client.put("/api/assistant/settings", json={"providers": {"custom": {"api_key": "••••••••1234", "model": "m-two"}}})
    assert client.a.settings.raw()["providers"]["custom"]["api_key"] == "sk-secret-1234"  # masked value never overwrites


def test_friendly_errors(client):
    client.fake.fail = 401
    _, ev = chat(client, "hi")
    err = [d for e, d in ev if e == "error"][0]["message"]
    assert "API key" in err and "Traceback" not in err
    client.fake.fail = 429
    _, ev = chat(client, "hi")
    assert "too many" in [d for e, d in ev if e == "error"][0]["message"]
    client.a.settings.update({"providers": {"custom": {"base_url": "http://127.0.0.1:9/v1"}}})
    _, ev = chat(client, "hi")
    assert "Cannot reach" in [d for e, d in ev if e == "error"][0]["message"]


def test_models_and_test_connection(client):
    assert client.get("/api/assistant/models").json()["models"] == ["m-one", "m-two"]
    assert client.post("/api/assistant/settings/test", json={}).json()["ok"]


@pytest.mark.parametrize("cmd,ext", [("/pdf", "pdf"), ("/ppt", "pptx"), ("/doc", "docx")])
def test_create_documents_from_llm_markdown(client, cmd, ext):
    client.fake.reply = "# Plan\n\n## Goals\n\n- First goal\n- Second goal\n\n## Table\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    _, ev = chat(client, f"{cmd} a project plan for a cloud migration")
    cards = [d for e, d in ev if e == "card"]
    f = cards[0]["file"]
    assert cards[0]["type"] == "file" and f["name"].endswith("." + ext) and cards[0]["theme"]["name"]
    dl = client.get(f"/api/assistant/files/{f['id']}/download")
    assert dl.status_code == 200 and len(dl.content) > 500
    if ext == "pdf":
        assert dl.content[:4] == b"%PDF"
    else:
        assert dl.content[:2] == b"PK"


def test_csv_xlsx_and_pasted_markdown_skip_llm(client):
    md = "# Sales\n\n| region | units |\n| --- | --- |\n| N | 5 |\n| S | 7 |\n"
    n = len(client.fake.requests)
    _, ev = chat(client, "/csv " + md)
    assert len(client.fake.requests) == n  # no model needed for content the user pasted
    f = [d for e, d in ev if e == "card"][0]["file"]
    assert client.get(f"/api/assistant/files/{f['id']}/download").content.startswith(b"\xef\xbb\xbf")
    _, ev = chat(client, "/xlsx " + md)
    assert [d for e, d in ev if e == "card"][0]["file"]["name"].endswith(".xlsx")


def test_ats_with_job_description(client):
    f = upload(client, "resume.txt", RESUME)
    _, ev = chat(client, "/ats", [f["id"]], {"job_description": "We need Kubernetes AWS Agile Terraform stakeholder management and Python for a program manager role leading teams."})
    card = [d for e, d in ev if e == "card"][0]
    assert card["type"] == "ats" and 0 < card["result"]["score"] <= 100 and card["result"]["has_job_description"]
    r = client.post("/api/assistant/tools/ats", json={"file_id": f["id"], "job_description": ""})
    assert r.status_code == 200


def test_ats_without_file_is_a_clear_message(client):
    _, ev = chat(client, "/ats")
    assert "Attach" in [d for e, d in ev if e == "error"][0]["message"]


def test_compare_and_analyze_flow(client):
    a = upload(client, "a.csv", b"id,qty\n1,5\n2,7\n")
    b = upload(client, "b.csv", b"id,qty\n1,5\n2,9\n3,1\n")
    _, ev = chat(client, "/compare", [a["id"], b["id"]])
    c = [d for e, d in ev if e == "card"][0]
    assert c["type"] == "compare" and not c["result"]["identical"]
    assert client.get(f"/api/assistant/files/{c['report']['id']}/download").status_code == 200
    _, ev = chat(client, "/analyze", [a["id"]])
    assert [d for e, d in ev if e == "card"][0]["result"]["tables"][0]["rows"] == 2


def test_image_generation_and_download(client):
    _, ev = chat(client, "/image a red square")
    c = [d for e, d in ev if e == "card"][0]
    assert c["type"] == "image" and c["width"] == 64
    prog = [d for e, d in ev if e == "progress"]
    assert prog and prog[-1]["fraction"] == 1.0 and all(0 <= p["fraction"] <= 1 for p in prog)
    r = client.get(f"/api/assistant/files/{c['file']['id']}/download", params={"inline": True})
    assert r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    r = client.post("/api/assistant/tools/image", json={"prompt": "ab"})
    assert r.status_code == 400 and "Describe" in r.json()["detail"]


def test_attachment_is_given_to_the_model(client):
    f = upload(client, "notes.txt", b"The launch date is 14 March.")
    chat(client, "When is the launch?", [f["id"]])
    body = client.fake.requests[-1][2]
    assert "14 March" in json.dumps(body)


def test_upload_rules(client):
    assert client.post("/api/assistant/files", files={"file": ("evil.exe", b"MZ")}).status_code == 415
    assert client.post("/api/assistant/files", files={"file": ("e.txt", b"")}).status_code == 400
    f = upload(client, "../../etc/pass wd.txt", b"x")
    assert "/" not in f["name"] and ".." not in f["name"]
    assert client.get("/api/assistant/files/nope/download").status_code == 404


def test_theme_catalog_and_create_tool(client):
    t = client.get("/api/assistant/themes", params={"purpose": "fintech investor pitch", "doc_type": "pptx"}).json()
    assert len(t["themes"]) >= 140 and t["recommended"] and t["recommended"][0]["reasons"]
    r = client.post("/api/assistant/tools/create", json={"format": "pptx", "markdown": "# Hi\n\n## One\n- a\n- b", "theme": t["recommended"][0]["id"]})
    assert r.status_code == 200 and r.json()["theme"]["id"] == t["recommended"][0]["id"]
    assert client.post("/api/assistant/tools/create", json={"format": "exe", "markdown": "x"}).status_code == 400
    assert client.post("/api/assistant/tools/create", json={"format": "csv", "markdown": "no table here"}).status_code == 400


def test_conversation_management(client):
    cid, _ = chat(client, "one")
    assert any(c["id"] == cid for c in client.get("/api/assistant/conversations").json())
    assert client.patch(f"/api/assistant/conversations/{cid}", json={"title": "Renamed"}).status_code == 200
    assert client.delete(f"/api/assistant/conversations/{cid}").status_code == 200
    assert client.get(f"/api/assistant/conversations/{cid}").status_code == 404


def test_llm_event_parsers():
    assert llm.parse_event("openai", {"choices": [{"delta": {"content": "x"}}]}) == "x"
    assert llm.parse_event("openai", {"choices": [{"delta": {}}]}) == ""
    assert llm.parse_event("anthropic", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "y"}}) == "y"
    assert llm.parse_event("anthropic", {"type": "message_start"}) == ""
    with pytest.raises(llm.LLMError):
        llm.parse_event("anthropic", {"type": "error", "error": {"message": "boom"}})


def test_studio_serves_assistant_window_and_api(data_dir, monkeypatch, tmp_path):
    from ltxps.state import build_state

    monkeypatch.setenv("LTXPS_ENGINE", "fake")
    monkeypatch.setenv("LTXPS_FAKE_VRAM_MB", "4096")
    ui = tmp_path / "aui"
    ui.mkdir()
    (ui / "index.html").write_text("<title>AI Assistant</title>")
    studio = build_state(TOKEN)
    a = build_assistant_state(studio.paths.root / "assistant", TOKEN)
    with TestClient(create_app(studio, None, a, ui), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        assert "AI Assistant" in c.get("/assistant-app/").text
        assert c.get("/api/assistant/info").status_code == 200
        assert c.get("/api/health").status_code == 200  # video studio API still there


JD = ("We are hiring a Senior Program Manager. Responsibilities: lead cross functional teams, own the roadmap, manage stakeholders and risk, run agile delivery, "
      "work with AWS, Kubernetes and Python tooling, report KPIs to leadership. Requirements: 5 years of program management, stakeholder management, agile, scrum, AWS, Kubernetes.")
TAILORED = ("# Asha K\nChennai, India | asha@example.com | +91 98765 43210\n\n## Summary\nProgram manager who leads cross functional teams with agile delivery on AWS and Kubernetes.\n\n"
            "## Skills\nProgram management, stakeholder management, agile, scrum, AWS, Kubernetes, Python, roadmap, KPIs\n\n## Experience\n### Program Manager, Acme\nJan 2021 - Present\n"
            "- Led a team of 10 and cut cycle time by 30%\n- Built AWS and Kubernetes platform for 40k users\n\n## Education\nB.E. 2017\n")


def test_tailor_resume_to_a_job_description_file(client):
    client.fake.reply = TAILORED
    r = upload(client, "resume.txt", RESUME)
    j = upload(client, "job-description.txt", JD.encode())
    cid, ev = chat(client, "tailor my resume as per this JD with high ATS score", [r["id"], j["id"]])
    assert not [d for e, d in ev if e == "error"], ev
    cards = [d for e, d in ev if e == "card"]
    f = next(c for c in cards if c["type"] == "file")["file"]
    assert f["name"].endswith(".pdf")
    a = next(c for c in cards if c["type"] == "ats")["result"]
    assert a["has_job_description"] and a["before_score"] is not None and a["score"] >= a["before_score"]


def test_tailor_with_the_job_description_pasted_in_the_message(client):
    client.fake.reply = TAILORED
    r = upload(client, "resume.txt", RESUME)
    _, ev = chat(client, "tailor this resume to the JD below as a word file. " + JD, [r["id"]])
    cards = [d for e, d in ev if e == "card"]
    assert next(c for c in cards if c["type"] == "file")["file"]["name"].endswith(".docx")


def test_tailor_asks_for_the_job_description_when_missing(client):
    r = upload(client, "resume.txt", RESUME)
    _, ev = chat(client, "tailor my resume for ATS", [r["id"]])
    assert any(e == "error" and "job description" in d["message"].lower() for e, d in ev)


def test_progress_estimate_rises_but_never_finishes_early():
    from ltxps.assistant.service import estimate_fraction

    vals = [estimate_fraction(t, "horde") for t in (0, 5, 20, 60, 600)]
    assert vals == sorted(vals) and vals[0] == 0 and vals[-1] < 0.93


# ------------------------------------------------------------------ 1.2.11: advisor, prompt enhancement, image providers
def test_advice_matches_the_pc(client):
    r = client.get("/api/assistant/ai/advice")
    assert r.status_code == 200
    d = r.json()
    assert d["local"]["model"] and d["free_online"][0]["id"] == "groq" and d["paid"][0]["model"] == "claude-sonnet-5-5"
    assert d["best"]["id"] and d["pc"]
    assert "ready" in d["current"]


def test_advisor_scales_with_hardware():
    from ltxps.advisor import advise

    small = advise(6, 0, "", False)
    mid = advise(23.7, 6, "RTX 4050", True)
    big = advise(64, 24, "RTX 4090", True)
    assert small["local"]["model"] == "llama3.2:1b" and small["best"]["id"] == "groq"  # weak PC: use a free online service
    assert mid["local"]["model"] == "qwen2.5:7b" and mid["best"]["id"] == "ollama"
    assert big["local"]["model"] == "qwen2.5:32b"
    keyed = advise(23.7, 6, "RTX 4050", True, {"anthropic": True})
    assert keyed["best"]["id"] == "anthropic"  # a connected key wins


def test_prompt_enhancer_uses_model_or_recipe():
    from ltxps.assistant import enhance

    better, how = enhance.enhance("a dragon", "image", lambda s, u: "A towering black dragon perched on a cliff at dawn, wings spread, volumetric light, detailed scales")
    assert how == "ai" and "dragon" in better and len(better) > 40
    fallback, how2 = enhance.enhance("a dragon", "image", None)
    assert how2 == "recipe" and "dragon" in fallback and "detailed" in fallback
    broken, how3 = enhance.enhance("a dragon", "video", lambda s, u: (_ for _ in ()).throw(RuntimeError("offline")))
    assert how3 == "recipe" and "motion" in broken
    assert enhance.enhance("x" * 700, "image", None)[1] == "none"


def test_prompt_enhance_route_works_offline(client):
    r = client.post("/api/assistant/prompt/enhance", json={"prompt": "a lighthouse at sunset", "kind": "image"})
    assert r.status_code == 200 and "lighthouse" in r.json()["prompt"]


def test_new_image_providers_listed():
    from ltxps.assistant import images

    assert {"huggingface", "together", "openai"} <= set(images.IMAGE_PROVIDERS)
    assert "Midjourney" in images.IMAGE_PROVIDERS["openai"]["help"]
