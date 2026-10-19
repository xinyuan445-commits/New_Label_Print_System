import { useState } from "react";

type Theme = "light" | "dark";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );

  const toggle = () => {
    const next: Theme = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("label-theme", next);
    setTheme(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded-md px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 hover:text-white"
      aria-label={theme === "light" ? "切换深色模式" : "切换浅色模式"}
      title={theme === "light" ? "切换深色模式" : "切换浅色模式"}
    >
      {theme === "light" ? "☀ 浅色" : "☾ 深色"}
    </button>
  );
}
