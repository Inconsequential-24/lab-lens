import { useEffect, useState } from "react";
import { LangContext, type Lang } from "./i18n";
import Header from "./components/Header";
import Home from "./pages/Home";
import Results from "./pages/Results";
import History from "./pages/History";
import { Staff, Evaluations } from "./pages/Evals";
import About from "./pages/About";

// Minimal hash router: #/, #/report/<id>?real=1, #/history, #/staff, #/evals, #/about
function useHash() {
  const [hash, setHash] = useState(() => window.location.hash || "#/");
  useEffect(() => {
    const on = () => {
      setHash(window.location.hash || "#/");
      window.scrollTo(0, 0);
      document.getElementById("main")?.focus();
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export default function App() {
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("lang") === "hi" ? "hi" : "en"));
  const hash = useHash();
  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem("lang", lang);
  }, [lang]);

  const [path, query = ""] = hash.slice(1).split("?");
  let page;
  const m = path.match(/^\/report\/([\w-]+)$/);
  if (m) page = <Results reportId={m[1]} real={new URLSearchParams(query).get("real") === "1"} />;
  else if (path === "/history") page = <History />;
  else if (path === "/staff") page = <Staff />;
  else if (path === "/evals") page = <Evaluations />;
  else if (path === "/about") page = <About />;
  else page = <Home />;

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      <a className="skip" href="#main">Skip to content</a>
      <Header path={path} />
      <main id="main" tabIndex={-1}>{page}</main>
      <Banner />
    </LangContext.Provider>
  );
}

function Banner() {
  // Always visible, both languages (PLAN section 3).
  return (
    <div className="banner" role="note">
      <span lang="en">This is not a diagnosis. Please talk to a doctor about your results.</span>
      <span lang="hi">यह निदान नहीं है। कृपया अपने परिणामों के बारे में डॉक्टर से बात करें।</span>
    </div>
  );
}
