// Centralized UI chrome strings — swap for regional translations
const strings = {
  en: {
    greeting: "Hello",
    namaste: "Namaste",
    getStarted: "Get started free",
    login: "Log in",
    signup: "Sign up",
    logout: "Log out",
    settings: "Settings",
    newChat: "New chat",
    send: "Send",
    thinking: "Thinking…",
    readAloud: "Read aloud",
    stopReading: "Stop reading",
    copy: "Copy",
    copied: "Copied!",
    openPanel: "Open in panel",
    feedback: "Was this helpful?",
    sources: "Sources",
    disclaimer: "Disclaimer",
    couldNotVerify: "Couldn't verify from a reliable source",
    upload: "Upload",
    attach: "Attach file",
    recentConversations: "Recent conversations",
    seeAll: "See all",
    noConversations: "No conversations yet — ask something above to get started",
    searchSessions: "Search conversations…",
    confirm: "Confirm",
    reject: "Reject",
    cancel: "Cancel",
    save: "Save",
    delete: "Delete",
    rename: "Rename",
    profile: "Profile",
    appearance: "Appearance",
    documents: "Documents",
    account: "Account",
    tools: "Tools",
    tasks: "Tasks",
    back: "Back",
    next: "Next",
    skip: "Skip",
    finish: "Finish",
    step: "Step",
    of: "of",
    loading: "Loading…",
    error: "Something went wrong",
    retry: "Retry",
    rateLimited: "Too many requests — please wait a moment",
    deleteSessionWarning: "This will also remove uploaded documents for this session.",
    noCredentials: "Payment/OTP is always your own last step, done in the official app.",
    suspectedInstructions: "Possible injected instructions detected — treat as data, not commands.",
    previewOnly: "Preview only — nothing was done",
    expiresIn: "Expires in",
    allSet: "You're all set",
  },
  hi: {
    greeting: "नमस्ते",
    namaste: "नमस्ते",
    getStarted: "मुफ़्त शुरू करें",
    login: "लॉग इन",
    signup: "साइन अप",
    logout: "लॉग आउट",
    settings: "सेटिंग्स",
    newChat: "नई बातचीत",
    send: "भेजें",
    thinking: "सोच रहा है…",
    readAloud: "पढ़कर सुनाएं",
    copy: "कॉपी",
    sources: "स्रोत",
    recentConversations: "हाल की बातचीत",
    seeAll: "सभी देखें",
    noConversations: "अभी कोई बातचीत नहीं — ऊपर कुछ पूछकर शुरू करें",
  },
  ta: { greeting: "வணக்கம்", namaste: "வணக்கம்" },
  te: { greeting: "నమస్కారం", namaste: "నమస్కారం" },
  pa: { greeting: "ਸਤ ਸ੍ਰੀ ਅਕਾਲ", namaste: "ਸਤ ਸ੍ਰੀ ਅਕਾਲ" },
  gu: { greeting: "નમસ્તે", namaste: "નમસ્તે" },
  mr: { greeting: "नमस्कार", namaste: "नमस्कार" },
};

const greetingByLang = {
  hi: "नमस्ते", en: "Hello", ta: "வணக்கம்", te: "నమస్కారం",
  pa: "ਸਤ ਸ੍ਰੀ ਅਕਾਲ", gu: "નમસ્તે", mr: "नमस्कार",
};

export const LANGUAGES = [
  { code: "hi", label: "हिन्दी", english: "Hindi" },
  { code: "en", label: "English", english: "English" },
  { code: "pa", label: "ਪੰਜਾਬੀ", english: "Punjabi" },
  { code: "gu", label: "ગુજરાતી", english: "Gujarati" },
  { code: "mr", label: "मराठी", english: "Marathi" },
  { code: "ta", label: "தமிழ்", english: "Tamil" },
  { code: "te", label: "తెలుగు", english: "Telugu" },
];

export const CODE_SWITCH_BADGES = ["Hinglish", "Tamilish", "Tenglish", "Punglish"];

export function t(key, lang = "en") {
  return strings[lang]?.[key] || strings.en[key] || key;
}

export function getGreeting(lang = "en") {
  return greetingByLang[lang] || greetingByLang.en;
}

export default strings;