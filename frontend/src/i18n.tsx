import { createContext, useContext } from "react";

export type Lang = "en" | "hi";

const en = {
  menu: "Menu", about_test: "About this test", row_note: "Note",
  h_signed_out: "Saved history is optional. Nothing is saved unless you tick the save box under a result. To see saved reports and trends, sign in with Google.",
  google_sign_in: "Sign in with Google", google_unavailable: "Google sign-in is not configured on this server yet.", sign_out: "Sign out",
  h_saved: "Saved reports", h_empty: "You have no saved reports.", h_tests: "tests", h_delete: "Delete", h_delete_all: "Delete all saved reports",
  h_confirm_one: "Delete the report dated {d}? This cannot be undone.", h_confirm_all: "Delete all saved reports and withdraw consent? This cannot be undone.",
  h_yes: "Yes, delete", h_cancel: "Cancel", h_deleted: "Deleted.", h_trends: "Results over time", h_pick: "Test",
  h_trend_note: "Each point is shown against the range printed on that report (shaded band). This chart shows values only; it does not judge changes. Talk to a doctor about what they mean.",
  h_diff_unit: "Different unit, shown separately (not compared)", h_critical: "Past the safety limit", h_point: "Point",
  s_date: "Report date", s_date_hint: "Please confirm or enter the date printed on the report.", s_date_req: "Please enter the report date.",
  s_date_future: "The date cannot be in the future.", s_date_old: "The date cannot be before 1990.", s_save: "Save to my history",
  s_saving: "Saving…", s_saved: "Saved to your history.", s_already: "This report is already saved", s_overlap: "Some tests are already saved for this date. Choose what to keep for each:",
  s_keep_new: "Keep new", s_keep_existing: "Keep existing", s_keep_both: "Keep both", s_existing: "Saved", s_new: "This report", s_resend: "Save with these choices",
  s_need_sign_in: "Saving needs Google sign-in.",
  nav_report: "My report", nav_history: "History", nav_staff: "Staff view", nav_evals: "Evaluations", nav_about: "About",
  status_pill: "Demos + private reports", sign_in: "Sign in", create_account: "Create account",
  a11y: "Accessibility: larger text and stronger contrast",
  eyebrow: "Your lab report, read slowly",
  headline: "Understand the numbers. Leave the diagnosis to your doctor.",
  intro: "Explore a public synthetic demo, or sign in to analyse your own lab report. LabLens compares results only with the ranges printed on that report, explains each result in plain language, and saves it to your history only if you choose.",
  choose_type: "Choose report type", type_demo: "Demo / synthetic", type_real: "My real report",
  drop: "Drop a report here or choose a file", drop_hint: "PDF, PNG or JPG, up to 10 MB",
  confirm_demo: "I confirm this report is synthetic and contains no real patient data.",
  confirm_real: "I understand this is not a diagnosis, and that my report is deleted within 60 minutes unless I choose to save it.",
  demo_note: "Synthetic demos are available without an account.", demo_note_sign: "Sign in", demo_note_rest: "to save results to your history.",
  real_note: "Real reports need you to sign in. Sign-in is not available in this demo yet.",
  explain: "Explain this report", working: "Reading your report…",
  err_unsupported_file_type: "Please choose a PDF, PNG or JPG file.", err_file_too_large: "The file is larger than 10 MB.",
  demos_title: "Or open a demo report", open: "Open", pdf: "PDF", tests: "tests", loading: "Loading…",
  cat_normal: "Normal", cat_abnormal: "Abnormal", cat_critical: "Critical", cat_held: "Held",
  not_diagnosis: "This is not a diagnosis. Please talk to a doctor about your results.",
  back: "Back to My report", urgent_title: "Urgent: please seek medical help today",
  rec_title: "What to do next", next_doctor_consult: "Talk to a doctor", next_follow_up_test_package: "Consider a follow-up test", next_no_action: "No action suggested by the rules",
  urg_none: "No urgency", urg_routine: "Routine", urg_soon: "Soon", urg_urgent: "Urgent",
  results_title: "Your results", col_test: "Test", col_value: "Value", col_unit: "Unit", col_range: "Range", col_flag: "Flag", col_severity: "Severity", col_evidence: "Evidence",
  verify: "Please verify", evidence_page: "page", flag_low: "Low", flag_normal: "Normal", flag_high: "High", flag_unknown: "Unknown",
  sev_normal: "Normal", sev_mild: "Mild", sev_marked: "Marked", sev_critical: "Critical", sev_unknown: "Unknown",
  explanation: "Explanation", template_note: "Shown from a safe template because the AI explanation was not available.",
  patterns: "Patterns", warnings: "Warnings", unrecognised: "Tests we did not recognise", partial: "Some parts of this report could not be read fully.",
  history_title: "History", history_body: "Sign in to save reports to your history. Saved history and trend charts are coming in a later milestone.",
  staff_title: "Staff view", evals_title: "Evaluations", about_title: "About LabLens",
  no_evals: "No evaluation results are available yet.", report_date: "Report date",
  save_sign_in: "Saving needs sign-in, which is not available in this demo yet. Nothing has been saved.",
};
type Dict = typeof en;

const hi: Dict = {
  menu: "मेनू", about_test: "इस जाँच के बारे में", row_note: "नोट",
  h_signed_out: "हिस्ट्री सेव करना वैकल्पिक है। जब तक आप परिणाम के नीचे सेव बॉक्स टिक नहीं करते, कुछ सेव नहीं होता। सेव की गई रिपोर्ट और ट्रेंड देखने के लिए Google से साइन इन करें।",
  google_sign_in: "Google से साइन इन करें", google_unavailable: "इस सर्वर पर अभी Google साइन इन सेट नहीं है।", sign_out: "साइन आउट",
  h_saved: "सेव की गई रिपोर्ट", h_empty: "आपकी कोई सेव की गई रिपोर्ट नहीं है।", h_tests: "जाँचें", h_delete: "डिलीट करें", h_delete_all: "सभी सेव की गई रिपोर्ट डिलीट करें",
  h_confirm_one: "{d} की रिपोर्ट डिलीट करें? इसे वापस नहीं लाया जा सकता।", h_confirm_all: "सभी सेव की गई रिपोर्ट डिलीट करें और सहमति वापस लें? इसे वापस नहीं लाया जा सकता।",
  h_yes: "हाँ, डिलीट करें", h_cancel: "रद्द करें", h_deleted: "डिलीट हो गया।", h_trends: "समय के साथ परिणाम", h_pick: "जाँच",
  h_trend_note: "हर बिंदु उसी रिपोर्ट पर छपी सीमा (छायांकित पट्टी) के साथ दिखाया गया है। यह चार्ट केवल मान दिखाता है; बदलाव का आकलन नहीं करता। इनके अर्थ के बारे में डॉक्टर से बात करें।",
  h_diff_unit: "अलग यूनिट, अलग से दिखाया गया (तुलना नहीं)", h_critical: "सुरक्षा सीमा से आगे", h_point: "बिंदु",
  s_date: "रिपोर्ट की तारीख़", s_date_hint: "कृपया रिपोर्ट पर छपी तारीख़ की पुष्टि करें या दर्ज करें।", s_date_req: "कृपया रिपोर्ट की तारीख़ दर्ज करें।",
  s_date_future: "तारीख़ भविष्य की नहीं हो सकती।", s_date_old: "तारीख़ 1990 से पहले की नहीं हो सकती।", s_save: "मेरी हिस्ट्री में सेव करें",
  s_saving: "सेव हो रहा है…", s_saved: "आपकी हिस्ट्री में सेव हो गया।", s_already: "यह रिपोर्ट पहले से सेव है", s_overlap: "इस तारीख़ की कुछ जाँचें पहले से सेव हैं। हर एक के लिए चुनें कि क्या रखना है:",
  s_keep_new: "नया रखें", s_keep_existing: "पुराना रखें", s_keep_both: "दोनों रखें", s_existing: "सेव किया हुआ", s_new: "यह रिपोर्ट", s_resend: "इन विकल्पों के साथ सेव करें",
  s_need_sign_in: "सेव करने के लिए Google साइन इन ज़रूरी है।",
  nav_report: "मेरी रिपोर्ट", nav_history: "हिस्ट्री", nav_staff: "स्टाफ़ व्यू", nav_evals: "मूल्यांकन", nav_about: "परिचय",
  status_pill: "डेमो + निजी रिपोर्ट", sign_in: "साइन इन", create_account: "अकाउंट बनाएँ",
  a11y: "सुलभता: बड़ा टेक्स्ट और गहरा कंट्रास्ट",
  eyebrow: "आपकी लैब रिपोर्ट, धीरे-धीरे पढ़ी गई",
  headline: "नंबर समझें। निदान अपने डॉक्टर पर छोड़ें।",
  intro: "एक सार्वजनिक सिंथेटिक डेमो देखें, या अपनी लैब रिपोर्ट के लिए साइन इन करें। LabLens परिणामों की तुलना केवल उसी रिपोर्ट पर छपी सीमा से करता है, हर परिणाम को आसान भाषा में समझाता है, और आपकी मर्ज़ी होने पर ही उसे हिस्ट्री में सेव करता है।",
  choose_type: "रिपोर्ट का प्रकार चुनें", type_demo: "डेमो / सिंथेटिक", type_real: "मेरी असली रिपोर्ट",
  drop: "रिपोर्ट यहाँ छोड़ें या फ़ाइल चुनें", drop_hint: "PDF, PNG या JPG, 10 MB तक",
  confirm_demo: "मैं पुष्टि करता/करती हूँ कि यह रिपोर्ट सिंथेटिक है और इसमें किसी असली मरीज़ का डेटा नहीं है।",
  confirm_real: "मैं समझता/समझती हूँ कि यह निदान नहीं है, और सेव न करने पर मेरी रिपोर्ट 60 मिनट के भीतर डिलीट हो जाती है।",
  demo_note: "सिंथेटिक डेमो बिना अकाउंट के उपलब्ध हैं।", demo_note_sign: "साइन इन", demo_note_rest: "करें ताकि परिणाम हिस्ट्री में सेव हों।",
  real_note: "असली रिपोर्ट के लिए साइन इन ज़रूरी है। इस डेमो में अभी साइन इन उपलब्ध नहीं है।",
  explain: "यह रिपोर्ट समझाएँ", working: "आपकी रिपोर्ट पढ़ी जा रही है…",
  err_unsupported_file_type: "कृपया PDF, PNG या JPG फ़ाइल चुनें।", err_file_too_large: "फ़ाइल 10 MB से बड़ी है।",
  demos_title: "या कोई डेमो रिपोर्ट खोलें", open: "खोलें", pdf: "PDF", tests: "जाँचें", loading: "लोड हो रहा है…",
  cat_normal: "सामान्य", cat_abnormal: "असामान्य", cat_critical: "गंभीर", cat_held: "रोकी गई",
  not_diagnosis: "यह निदान नहीं है। कृपया अपने परिणामों के बारे में डॉक्टर से बात करें।",
  back: "मेरी रिपोर्ट पर वापस", urgent_title: "ज़रूरी: कृपया आज ही चिकित्सा सहायता लें",
  rec_title: "आगे क्या करें", next_doctor_consult: "डॉक्टर से बात करें", next_follow_up_test_package: "फ़ॉलो-अप जाँच पर विचार करें", next_no_action: "नियमों के अनुसार कोई कदम ज़रूरी नहीं",
  urg_none: "कोई जल्दी नहीं", urg_routine: "सामान्य", urg_soon: "जल्द", urg_urgent: "तुरंत",
  results_title: "आपके परिणाम", col_test: "जाँच", col_value: "मान", col_unit: "यूनिट", col_range: "सीमा", col_flag: "फ़्लैग", col_severity: "गंभीरता", col_evidence: "स्रोत",
  verify: "कृपया जाँच लें", evidence_page: "पेज", flag_low: "कम", flag_normal: "सामान्य", flag_high: "ज़्यादा", flag_unknown: "अज्ञात",
  sev_normal: "सामान्य", sev_mild: "हल्का", sev_marked: "स्पष्ट", sev_critical: "गंभीर", sev_unknown: "अज्ञात",
  explanation: "व्याख्या", template_note: "AI व्याख्या उपलब्ध न होने के कारण सुरक्षित टेम्पलेट से दिखाया गया।",
  patterns: "पैटर्न", warnings: "चेतावनियाँ", unrecognised: "जिन जाँचों को हम पहचान नहीं पाए", partial: "इस रिपोर्ट के कुछ हिस्से पूरी तरह पढ़े नहीं जा सके।",
  history_title: "हिस्ट्री", history_body: "रिपोर्ट को हिस्ट्री में सेव करने के लिए साइन इन करें। सेव की गई हिस्ट्री और ट्रेंड चार्ट बाद के चरण में आएँगे।",
  staff_title: "स्टाफ़ व्यू", evals_title: "मूल्यांकन", about_title: "LabLens के बारे में",
  no_evals: "अभी कोई मूल्यांकन परिणाम उपलब्ध नहीं है।", report_date: "रिपोर्ट की तारीख़",
  save_sign_in: "सेव करने के लिए साइन इन ज़रूरी है, जो इस डेमो में अभी उपलब्ध नहीं है। कुछ भी सेव नहीं हुआ है।",
};

// Consent wording from PLAN.md section 10 (notice version 2026-11-v1). Hindi needs a fluent reader's check.
export const consent = {
  en: { title: "Save this report to my history", body: "If you tick this box, we will save the test results from this report (test names, values, units, reference ranges, flags and the report date) to your account, so you can see your past reports and how your results change. We do not save the file you uploaded or your name. You can delete one report or all of your saved reports at any time from My history. If you don't tick this box, your report is deleted within 60 minutes. Ticking this box is optional and does not change the explanation you receive." },
  hi: { title: "यह रिपोर्ट मेरी हिस्ट्री में सेव करें", body: "अगर आप यह बॉक्स टिक करते हैं, तो हम इस रिपोर्ट के जाँच परिणाम (जाँच के नाम, मान, यूनिट, संदर्भ सीमा, फ़्लैग और रिपोर्ट की तारीख़) आपके अकाउंट में सेव करेंगे, ताकि आप अपनी पिछली रिपोर्ट और अपने परिणामों में बदलाव देख सकें। हम आपकी अपलोड की गई फ़ाइल या आपका नाम सेव नहीं करते। आप मेरी हिस्ट्री में जाकर कभी भी एक रिपोर्ट या अपनी सभी सेव की गई रिपोर्ट डिलीट कर सकते हैं। अगर आप यह बॉक्स टिक नहीं करते, तो आपकी रिपोर्ट 60 मिनट के भीतर डिलीट हो जाती है। यह बॉक्स टिक करना ज़रूरी नहीं है और इससे आपको मिलने वाली व्याख्या नहीं बदलती।" },
} as const;

export const dicts: Record<Lang, Dict> = { en, hi };
export type Key = keyof Dict;

export const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });
export function useT() {
  const { lang } = useContext(LangContext);
  return (k: Key) => dicts[lang][k];
}
