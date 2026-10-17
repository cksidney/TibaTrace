import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Icon } from './icons.js';

/** Shared keyboard and focus behavior for forms launched from a workspace. */
export function IntakeModal({ title, children, busy = false, onClose }: {
  readonly title: string;
  readonly children: ReactNode;
  readonly busy?: boolean;
  readonly onClose: () => void;
}) {
  const titleId = useId();
  const panel = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const saving = useRef(busy);
  saving.current = busy;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const controls = () => Array.from(panel.current?.querySelectorAll<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href], [tabindex="0"]',
    ) ?? []).filter((element) => !element.matches(':disabled') && !element.closest('[hidden]'));
    (controls().find((element) => element.matches('input, select, textarea')) ?? panel.current)?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!saving.current) close.current();
      }
      if (event.key === 'Tab') {
        const items = controls();
        const first = items[0];
        const last = items[items.length - 1];
        if (!first || !last) { event.preventDefault(); panel.current?.focus(); }
        else if (event.shiftKey && (document.activeElement === first || !panel.current?.contains(document.activeElement))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !panel.current?.contains(document.activeElement))) {
          event.preventDefault(); first.focus();
        }
      }
    };
    document.addEventListener('keydown', keydown, true);
    return () => {
      document.removeEventListener('keydown', keydown, true);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <div className="business-dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !busy) onClose();
  }}>
    <section ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy} className="business-dialog intake-modal" tabIndex={-1}>
      <header><h2 id={titleId}>{title}</h2><button aria-label={`Close ${title}`} type="button" disabled={busy} onClick={onClose}><Icon name="close" /></button></header>
      {children}
    </section>
  </div>;
}

/** Validation stays native; a refused/uncertain save retains the same draft. */
export function IntakeForm({ title, label = title, submitLabel = 'Save', children, submit, error, disabled = false }: {
  readonly title: string;
  readonly label?: string;
  readonly submitLabel?: string;
  readonly children: ReactNode;
  readonly submit: () => Promise<boolean>;
  readonly error?: string;
  readonly disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const inFlight = useRef(false);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setFailure('');
    try { if (await submit()) setOpen(false); }
    catch (cause) { setFailure(cause instanceof Error ? cause.message : 'The record could not be saved.'); }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <>
    <button className="secondary-button" type="button" disabled={disabled} onClick={() => { setFailure(''); setOpen(true); }}>{label}</button>
    {open && <IntakeModal title={title} busy={busy} onClose={() => setOpen(false)}>
      <form onSubmit={(event) => void save(event)}><fieldset disabled={busy} className="intake-fields">
        <div className="stocktake-form-grid">{children}</div>
        {failure || error ? <p className="business-dialog-error" role="alert">{failure || error}</p> : null}
        <footer><button className="secondary-button" type="button" onClick={() => setOpen(false)}>Cancel</button><button className="primary-button" type="submit">{busy ? 'Saving…' : submitLabel}</button></footer>
      </fieldset></form>
    </IntakeModal>}
  </>;
}
