import { useT } from "../i18n";

export default function About() {
  const t = useT();
  return (
    <div className="wrap narrow prose">
      <h1 className="display small">{t("about_title")}</h1>
      <p>LabLens reads a lab report (PDF, PNG or JPG) and explains each result in plain English and Hindi. It compares each value only with the reference range printed on that report, flags results outside it, and suggests a next step using fixed, written rules.</p>
      <h2>Not a diagnosis</h2>
      <p>LabLens does not diagnose, name diseases or suggest treatment. If any value is at a critical level, an urgent message is shown first. Please talk to a doctor about your results.</p>
      <h2>Synthetic data</h2>
      <p>The demo reports are synthetic: generated for testing, with no real patient data. Real uploads are deleted within 60 minutes unless you choose to save them after signing in.</p>
      <h2>How AI is used</h2>
      <p>A language model reads the report and drafts the explanation. Flags, severity, critical values and the next step come from deterministic rules, and every sentence in the explanation must cite a test or glossary entry. If the AI is unavailable or fails a safety check, a safe template is shown instead. Evaluation results are on the Evaluations page.</p>
    </div>
  );
}
