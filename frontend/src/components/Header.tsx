import { useContext, useEffect, useState } from "react";
import { LangContext, useT, type Key } from "../i18n";

const NAV: [string, Key][] = [["/", "nav_report"], ["/history", "nav_history"], ["/staff", "nav_staff"], ["/evals", "nav_evals"], ["/about", "nav_about"]];

export default function Header({ path }: { path: string }) {
  const t = useT();
  const { lang, setLang } = useContext(LangContext);
  const [large, setLarge] = useState(() => localStorage.getItem("a11y") === "1");
  useEffect(() => {
    document.documentElement.classList.toggle("a11y-large", large);
    localStorage.setItem("a11y", large ? "1" : "0");
  }, [large]);
  const active = (p: string) => (p === "/" ? path === "/" || path.startsWith("/report") : path === p);

  return (
    <header className="site-header">
      <div className="wrap header-inner">
        <a href="#/" className="logo" aria-label="LabLens home"><span className="logo-mark" aria-hidden="true" />LabLens</a>
        <nav aria-label="Main">
          <ul className="nav">
            {NAV.map(([p, k]) => (
              <li key={p}><a href={`#${p}`} className={active(p) ? "active" : ""} aria-current={active(p) ? "page" : undefined}>{t(k)}</a></li>
            ))}
          </ul>
        </nav>
        <div className="header-tools">
          <span className="pill-status"><span className="dot" aria-hidden="true" />{t("status_pill")}</span>
          <div className="lang-toggle" role="group" aria-label="Language">
            <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
            <button type="button" aria-pressed={lang === "hi"} onClick={() => setLang("hi")} lang="hi">हिंदी</button>
          </div>
          {/* Sign-in arrives with saved history (milestone 12). */}
          <a className="btn-outline small" href="#/history">{t("sign_in")}</a>
          <a className="link-teal" href="#/history">{t("create_account")}</a>
          <button type="button" className="icon-btn" aria-pressed={large} aria-label={t("a11y")} title={t("a11y")} onClick={() => setLarge(!large)}>
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="4" r="2" /><path d="M5 8h14M12 8v6m0 0-4 7m4-7 4 7" /></svg>
          </button>
        </div>
      </div>
    </header>
  );
}
