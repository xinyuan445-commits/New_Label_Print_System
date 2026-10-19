import { useTranslation } from "react-i18next";

const LANGUAGES = [
  { code: "zh", flag: "🇨🇳", label: "中文", short: "中文" },
  { code: "pl", flag: "🇵🇱", label: "Polski", short: "PL" },
  { code: "en", flag: "🇬🇧", label: "English", short: "EN" },
];

export function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const current = i18n.language.slice(0, 2);

  return (
    <div className="flex gap-1 rounded-md border border-slate-800 bg-slate-900 p-0.5">
      {LANGUAGES.map((lang) => (
        <button
          key={lang.code}
          type="button"
          onClick={() => void i18n.changeLanguage(lang.code)}
          className={[
            "rounded px-2 py-1 text-xs font-medium transition-colors",
            current === lang.code
              ? "bg-indigo-600 text-white"
              : "text-slate-400 hover:text-slate-100",
          ].join(" ")}
          title={lang.label}
        >
          {lang.flag} {lang.short}
        </button>
      ))}
    </div>
  );
}
