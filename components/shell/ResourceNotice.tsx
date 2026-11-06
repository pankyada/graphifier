"use client";

import { CircleAlert, Info, TriangleAlert, X } from "lucide-react";

interface ResourceNoticeProps {
  tone: "info" | "warn" | "bad";
  title: string;
  text: string;
  onDismiss?: () => void;
}

/** Inline notice. The title carries the meaning; colour is secondary. */
export function ResourceNotice({ tone, title, text, onDismiss }: ResourceNoticeProps) {
  const Icon = tone === "bad" ? CircleAlert : tone === "warn" ? TriangleAlert : Info;
  return (
    <div className={`banner ${tone}`} role={tone === "bad" ? "alert" : "status"}>
      <Icon className="icon" aria-hidden="true" />
      <div className="banner-body">
        <span className="banner-title">{title}</span> <span>{text}</span>
      </div>
      {onDismiss ? (
        <button type="button" className="icon-btn" aria-label={`Dismiss: ${title}`} onClick={onDismiss}>
          <X className="icon" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
