"use client";

import type { ReportSection } from "@/types/artifact";
import { extractReportSubheadings, reportAnchorId } from "@/lib/report-navigation";

interface Props {
  sections: ReportSection[];
  activeSection: string | null;
  onSelect: (anchorId: string) => void;
}

export function OutlineNav({ sections, activeSection, onSelect }: Props) {
  return (
    <nav className="sticky top-4 max-h-[calc(100vh-10rem)] space-y-1 overflow-y-auto pr-1">
      <h3 className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider mb-3 font-medium">
        章节导航
      </h3>
      {sections
        .map((section) => {
          const anchorId = reportAnchorId("section", section.heading);
          const isActive = activeSection === anchorId;
          return (
            <div key={section.heading}>
              <button
                onClick={() => onSelect(anchorId)}
                className={`block w-full text-left text-xs py-1.5 pl-3 rounded-lg transition-colors border-l-2 ${
                  isActive
                    ? "border-emerald-500 text-emerald-500 bg-emerald-500/5"
                    : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--border)]"
                }`}
              >
                {section.heading}
              </button>
              {extractReportSubheadings(section.content).map((subheading) => {
                const subsectionAnchorId = reportAnchorId("subsection", subheading);
                const isSubsectionActive = activeSection === subsectionAnchorId;
                return (
                  <button
                    key={`${section.heading}-${subsectionAnchorId}`}
                    onClick={() => onSelect(subsectionAnchorId)}
                    className={`block w-full text-left text-[11px] py-1 pl-6 rounded-lg transition-colors ${
                      isSubsectionActive
                        ? "text-emerald-500 bg-emerald-500/5"
                        : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                    }`}
                  >
                    {subheading}
                  </button>
                );
              })}
            </div>
          );
        })}
    </nav>
  );
}
