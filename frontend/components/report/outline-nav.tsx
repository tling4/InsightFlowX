"use client";

import type { ReportSection } from "@/types/artifact";

interface Props {
  sections: ReportSection[];
  activeSection: string | null;
  onSelect: (heading: string) => void;
}

export function OutlineNav({ sections, activeSection, onSelect }: Props) {
  return (
    <nav className="sticky top-4 space-y-1">
      <h3 className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider mb-3 font-medium">
        章节导航
      </h3>
      {sections
        .filter((s) => s.level === 2)
        .map((section) => {
          const isActive = activeSection === section.heading;
          return (
            <button
              key={section.heading}
              onClick={() => onSelect(section.heading)}
              className={`block w-full text-left text-xs py-1.5 pl-3 rounded-lg transition-colors border-l-2 ${
                isActive
                  ? "border-emerald-500 text-emerald-500 bg-emerald-500/5"
                  : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--border)]"
              }`}
            >
              {section.heading}
            </button>
          );
        })}
    </nav>
  );
}
