"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "narrow" | "default" | "wide";
}

/**
 * Native modal dialog: focus is trapped and Escape closes it. Children mount
 * only while open, so each opening starts from a clean form state.
 */
export function Dialog({ open, onClose, title, children, footer, size = "default" }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const sizeClass = size === "wide" ? " wide" : size === "narrow" ? " narrow" : "";

  return (
    <dialog
      ref={ref}
      className={`dialog${sizeClass}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {open ? (
        <div className="dialog-form">
          <div className="dialog-head">
            <h2 id={titleId} className="dialog-title">
              {title}
            </h2>
            <button type="button" className="icon-btn" aria-label="Close dialog" onClick={onClose}>
              <X className="icon" aria-hidden="true" />
            </button>
          </div>
          <div className="dialog-body">{children}</div>
          {footer ? <div className="dialog-foot">{footer}</div> : <span />}
        </div>
      ) : null}
    </dialog>
  );
}
