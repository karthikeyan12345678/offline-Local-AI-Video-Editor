from ltxps.editor import voicecast


def test_persona_from_words():
    assert voicecast.persona_from_text("an old woman walks in the garden") == "old_woman"
    assert voicecast.persona_from_text("a little girl laughs") == "girl"
    assert voicecast.persona_from_text("a young boy runs") == "boy"
    assert voicecast.persona_from_text("a man in a suit speaks") == "man"
    assert voicecast.persona_from_text("grandfather tells a story") == "old_man"
    assert voicecast.persona_from_text("a lion in the grass") is None


def test_choice_order_is_asked_then_picture_then_words_then_man():
    assert voicecast.choose("old_man", "a girl", "woman") == "old_man"
    assert voicecast.choose("auto", "a man", "girl") == "girl"
    assert voicecast.choose("auto", "a woman speaks") == "woman"
    assert voicecast.choose("auto", "a lion") == "man"


def test_vision_reply_becomes_a_persona():
    assert voicecast.persona_from_vision(lambda q: '{"gender":"female","age":"old"}') == "old_woman"
    assert voicecast.persona_from_vision(lambda q: 'Sure! {"gender":"male","age":"child"}') == "boy"
    assert voicecast.persona_from_vision(lambda q: '{"gender":"none","age":"adult"}') is None
    assert voicecast.persona_from_vision(lambda q: "I cannot see pictures") is None

    def boom(q):
        raise RuntimeError("no vision")

    assert voicecast.persona_from_vision(boom) is None and voicecast.persona_from_vision(None) is None


def test_voice_and_shape_follow_the_age_and_gender():
    voices = ["Microsoft David Desktop", "Microsoft Zira Desktop"]
    girl, woman, old_woman = (voicecast.plan(p, voices) for p in ("girl", "woman", "old_woman"))
    assert girl["voice"] == woman["voice"] == old_woman["voice"] == "Microsoft Zira Desktop"
    assert girl["pitch"] > woman["pitch"] > old_woman["pitch"] and old_woman["tremolo"] > 0 and old_woman["tempo"] < 1
    assert voicecast.plan("old_man", voices)["voice"] == "Microsoft David Desktop"
    only_male = voicecast.plan("woman", ["Microsoft David Desktop"])
    assert only_male["pitch"] > 1.1 and "pitch was shifted" in only_male["note"]  # no female voice: the male one is moved up
    assert voicecast.audio_filter(voicecast.plan("man", voices)) == ""
    assert "asetrate" in voicecast.audio_filter(girl) and "tremolo" in voicecast.audio_filter(old_woman)
