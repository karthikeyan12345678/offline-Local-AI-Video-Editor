/** True in the website build ("vite build --mode web"): there is no server, everything runs in the browser. */
export const IS_WEB = import.meta.env.VITE_WEB === "1";
