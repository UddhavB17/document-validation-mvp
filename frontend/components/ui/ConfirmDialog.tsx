"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const isConfirmingRef = useRef(false);
  const [isConfirming, setIsConfirming] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    const previousActiveElement = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => cancelButtonRef.current?.focus(), 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isConfirmingRef.current) {
        onCancel();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusableElements = dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (!focusableElements?.length) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [onCancel, open]);

  useEffect(() => {
    if (open) {
      isConfirmingRef.current = false;
      setIsConfirming(false);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const handleConfirm = async () => {
    isConfirmingRef.current = true;
    setIsConfirming(true);
    try {
      await onConfirm();
    } finally {
      isConfirmingRef.current = false;
      setIsConfirming(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation">
      <section ref={dialogRef} className="dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-description">
        <div className="dialog__eyebrow">Confirm action</div>
        <h2 id="confirm-dialog-title" className="dialog__title">{title}</h2>
        <div id="confirm-dialog-description" className="dialog__description">{description}</div>
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={isConfirming} ref={cancelButtonRef}>
            {cancelLabel}
          </button>
          <button type="button" className="button button--danger" onClick={() => void handleConfirm()} disabled={isConfirming}>
            {isConfirming ? "Working…" : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
