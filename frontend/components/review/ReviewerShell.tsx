"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import "./reviewer.css";

export type ReviewerTab = "queue" | "saved";

export function ReviewerShell({
  tab,
  onTabChange,
  queueCount,
  savedCount,
  children,
  crumb,
  kicker = "Reviewer",
  title = "Loan file reviews",
  lede = "Work through the queue, save findings on each file, then return to Saved reviews to see who finished a file and which problems were kept.",
}: {
  tab?: ReviewerTab;
  onTabChange?: (tab: ReviewerTab) => void;
  queueCount?: number | null;
  savedCount?: number | null;
  children: ReactNode;
  crumb?: ReactNode;
  kicker?: string;
  title?: string;
  lede?: string;
}) {
  return (
    <div className="reviewer">
      <div className="reviewer__frame">
        {crumb}
        <p className="reviewer__kicker">{kicker}</p>
        <h1 className="reviewer__title">{title}</h1>
        <p className="reviewer__lede">{lede}</p>
        {tab && onTabChange ? (
          <nav className="reviewer__nav" aria-label="Reviewer sections">
            <button
              type="button"
              className={`reviewer__nav-item${tab === "queue" ? " is-active" : ""}`}
              aria-current={tab === "queue" ? "page" : undefined}
              onClick={() => onTabChange("queue")}
            >
              Queue
              {typeof queueCount === "number" ? (
                <span className="reviewer__nav-count">{queueCount}</span>
              ) : null}
            </button>
            <button
              type="button"
              className={`reviewer__nav-item${tab === "saved" ? " is-active" : ""}`}
              aria-current={tab === "saved" ? "page" : undefined}
              onClick={() => onTabChange("saved")}
            >
              Saved reviews
              {typeof savedCount === "number" ? (
                <span className="reviewer__nav-count">{savedCount}</span>
              ) : null}
            </button>
          </nav>
        ) : null}
        {children}
      </div>
    </div>
  );
}

export function ReviewerCrumb({
  items,
}: {
  items: Array<{ label: string; href?: string }>;
}) {
  return (
    <nav className="reviewer__crumb" aria-label="Breadcrumb">
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`} style={{ display: "contents" }}>
          {index > 0 ? <span className="reviewer__crumb-sep">/</span> : null}
          {item.href ? <Link href={item.href}>{item.label}</Link> : <span>{item.label}</span>}
        </span>
      ))}
    </nav>
  );
}
