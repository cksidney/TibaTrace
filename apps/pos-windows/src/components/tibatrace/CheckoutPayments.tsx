import { useCallback, useEffect, useRef, useState } from 'react';
import { retailCashChangeDue } from '@dawatrace/shared/retail/index.js';
import { formatMoney } from '@dawatrace/shared/money.js';
import type { DurableActionJournal } from '@dawatrace/shared/dispensing/index.js';
import { PosIcon } from './PosIcon.js';

interface Tender { id:string; tender_type:string; status:string; allocated_amount:string; effective_settled:string; cash_received:string|null; change_due:string|null; external_reference:string; command_key:string; }
interface Checkout { can_request_void?:boolean; can_approve_void?:boolean; voids?:readonly {id:string; method:string; amount:string; reason:string; own_request:boolean}[]; completion_error?:string; sale_state?:string; source_id:string; amount_due:string|null; currency:string; methods:readonly {type:string; label:string; available:boolean; blocker:string}[]; intent:null|{amount_remaining:string; effective_settled:string; status:string; tenders:readonly Tender[]}; fiscal:{status:string; message:string; receipt:null|Record<string,unknown>}; }
export function CheckoutPayments({apiFetch, path, sourceId, deviceId, journal, onChanged, onBusyChange}: {
  readonly apiFetch:typeof fetch; readonly path:string; readonly sourceId:string; readonly deviceId:string;
  readonly journal:DurableActionJournal|null; readonly onChanged:()=>Promise<unknown>; readonly onBusyChange?:(busy:boolean)=>void;
}) {
  const [checkout,setCheckout]=useState<Checkout|null>(null);
  const [method,setMethod]=useState('CASH'); const [amount,setAmount]=useState('');
  const [received,setReceived]=useState(''); const [reference,setReference]=useState(''); const [phone,setPhone]=useState('');
  const [voidReason,setVoidReason]=useState(''); const [voidReferences,setVoidReferences]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState(false); const [notice,setNotice]=useState(''); const inFlight=useRef(false);
  const sourceKey=path.includes('/retail/')?`retail:${sourceId}`:sourceId;
  const pending=journal?.entries.filter(e=>e.episodeId===sourceKey&&['PENDING','IN_FLIGHT','NEEDS_RECONCILIATION'].includes(e.state))??[];
  const load=useCallback(async()=>{const r=await apiFetch(path);if(!r.ok)throw Error('Payment status could not be read. Refresh before collecting.'); const data=await r.json() as Checkout;setCheckout(data);return data;},[apiFetch,path]);
  useEffect(()=>{void load().catch(e=>setNotice(String(e.message)));},[load]);
  const balance=checkout?.intent?.amount_remaining??checkout?.amount_due??null;
  const execute=async(operation:()=>Promise<void>)=>{if(inFlight.current)return;inFlight.current=true;setBusy(true);onBusyChange?.(true);setNotice('');try{await operation();}catch(e){setNotice(e instanceof Error?e.message:String(e));}finally{inFlight.current=false;setBusy(false);onBusyChange?.(false);}};
  const send=async(payload:Record<string,unknown>)=>{
    let response:Response;
    try {response=await apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
    catch{return{kind:'unknown' as const,message:'Outcome unknown. Check the original payment before collecting again.'};}
    if(!response.ok){
      const data:unknown=await response.json().catch(()=>null);
      const messages=typeof data==='string'?[data]:Array.isArray(data)?data:data&&typeof data==='object'?Object.values(data).flat():[];
      const detail=messages.filter((value):value is string=>typeof value==='string').join(' ');
      return{kind:response.status>=500?'unknown' as const:'blocked' as const,message:response.status>=500?'Outcome unknown. Check the original payment before collecting again.':response.status===403?'Your account is not authorised for this payment action.':detail||'Payment was refused. Refresh the sale and review its requirements.'};
    }
    const data=await response.json() as Checkout;setCheckout(data);
    return{kind:'ok' as const};
  };
  const collect=(original?:Record<string,unknown>)=>void execute(async()=>{
    if(!journal)throw Error('Secure payment recovery is unavailable. No collection was sent.');
    const payload=original??{operation:method==='MPESA'?'initiate':'collect',device_id:deviceId,tender_type:method,amount:amount||balance,cash_received:method==='CASH'?(received||amount||balance):'0',reference,phone_number:phone,idempotency_key:crypto.randomUUID()};
    const key=String(payload.idempotency_key);
    if (!navigator.onLine && !original) {
      if (method !== 'CASH') throw Error('Card and provider payments need connectivity.');
      await journal.stage({id:crypto.randomUUID(),type:'PAYMENT',episodeId:sourceKey,idempotencyKey:key,payload:{...payload,checkout_path:path}});
      setNotice('Cash command saved securely on this till. The sale is NOT confirmed and stock is NOT released. Reconnect and check before retrying the original command.');
      return;
    }
    const result=await journal.run({id:crypto.randomUUID(),type:'PAYMENT',episodeId:sourceKey,idempotencyKey:key,payload:{...payload,checkout_path:path}},()=>send(payload));
    if(result.kind==='ok'){setAmount('');setReceived('');setReference('');setNotice(method==='MPESA'?'Request recorded. Check provider status; a request is not a payment.':'Payment recorded.');await onChanged();}
    else setNotice(result.message??'Payment needs review.');
  });
  const recover=()=>void execute(async()=>{
    const current=await load();
    if(!journal)return;
    for(const entry of pending){
      const tender=current.intent?.tenders.find(t=>t.command_key===entry.idempotencyKey);
      if(entry.state==='NEEDS_RECONCILIATION')await journal.reconcile(entry.id,!!tender);
    }
    setNotice('Original commands checked. Recorded payments stay recorded; absent commands keep the same retry key.');
    await onChanged();
  });
  const command=(operation:'query'|'fiscal'|'finish'|'request_void'|'complete_void')=>void execute(async()=>{const result=await send({operation,device_id:deviceId,reason:voidReason,payment_references:voidReferences});if(result.kind!=='ok')throw Error(result.message);await onChanged();});
  const keyed=Number(amount||balance);
  const validAmount=/^\d{1,13}(?:\.\d{1,2})?$/.test(amount||balance||'');
  const changeDue=retailCashChangeDue(amount||balance||'',received||amount||balance||'');
  const available=checkout?.methods.find(m=>m.type===method)?.available??false;
  const disabled=busy||checkout?.intent?.status==='REVERSAL_PENDING'||pending.length>0||!available||balance===null||!validAmount||!Number.isFinite(keyed)||keyed<=0||keyed>Number(balance)||(method==='CARD'&&!reference.trim())||(method==='CASH'&&changeDue===null)||(method==='MPESA'&&!phone.trim());
  const fullySettled=checkout?.intent?.status==='SETTLED'&&Number(checkout.intent.effective_settled)>0&&balance!==null&&Number(balance)===0;
  const pendingProvider=checkout?.intent?.tenders.some(t=>t.status==='PENDING');
  return <section className="pos-checkout" aria-label="Payment checkout">
    <header className="pos-page-heading"><div><span className="pos-eyebrow">Secure checkout</span><h2>Payment</h2><p>Pay in full or enter a part amount and complete the balance with another method.</p></div><button className="pos-button" disabled={busy} onClick={()=>void execute(async()=>{await load();await onChanged();})}><PosIcon name="sync" size={16}/>Refresh</button></header>
    <div className="pos-payment-totals"><div><small>Total due</small><strong>{checkout?.amount_due?formatMoney(checkout.amount_due,checkout.currency):'Not priced'}</strong></div><div><small>Settled</small><strong>{formatMoney(checkout?.intent?.effective_settled??'0',checkout?.currency??'KES')}</strong></div><div><small>Remaining</small><strong>{balance===null?'—':formatMoney(balance,checkout?.currency??'KES')}</strong></div></div>
    {notice&&<p role="status" className="pos-payment-notice">{notice}</p>}
    {pending.length>0&&<div className="pos-payment-notice" role="alert"><b>A previous payment needs recovery.</b><p>Check its original command before collecting any more money.</p><button className="pos-button" disabled={busy} onClick={recover}>Check original payment</button>{pending.filter(e=>e.state==='PENDING').map(e=><button key={e.id} className="pos-button" disabled={busy} onClick={()=>collect(e.payload)}>Retry original command</button>)}</div>}
    {Number(balance)>0&&<><div className="pos-tender-options" role="group" aria-label="Payment method">{checkout?.methods.map(m=><button key={m.type} type="button" aria-pressed={method===m.type} disabled={busy||!m.available} title={m.blocker} onClick={()=>setMethod(m.type)}>{m.label}</button>)}</div>
      {checkout?.methods.filter(m=>!m.available).map(m=><p key={m.type} className="pos-payment-help">{m.label}: {m.blocker}</p>)}
      <div className="pos-payment-fields"><label>Amount to settle<input inputMode="decimal" value={amount} placeholder={balance??'0.00'} disabled={busy||pending.length>0} onChange={e=>setAmount(e.target.value)}/></label>
      {method==='CASH'&&<label>Cash received<input inputMode="decimal" value={received} placeholder={amount||balance||'0.00'} disabled={busy} onChange={e=>setReceived(e.target.value)}/></label>}
      {method==='CARD'&&<label>Terminal approval reference<input value={reference} disabled={busy} onChange={e=>setReference(e.target.value)}/></label>}
      {method==='MPESA'&&<label>Customer phone<input type="tel" value={phone} disabled={busy} onChange={e=>setPhone(e.target.value)}/></label>}</div>
      {method==='CASH'&&<p className="pos-payment-help">Change due: {changeDue!==null?formatMoney(changeDue,checkout?.currency??'KES'):'Enter sufficient cash'}</p>}
      {method==='CARD'&&<p className="pos-payment-help">Take payment on the external card terminal first, then record its approval reference. No card number or PIN is entered here.</p>}
      <button type="button" className="pos-start-sale" disabled={disabled} onClick={()=>collect()}>{busy?'Confirming…':!navigator.onLine&&method==='CASH'?'Save pending cash command':method==='MPESA'?'Request M-PESA payment':'Confirm payment'}</button></>}
    {checkout?.intent?.tenders.length? <div className="pos-settlement-list" aria-label="Recorded payment parts">{checkout.intent.tenders.map(t=><article key={t.id}><div><b>{t.tender_type}</b><span>{t.status.replace(/_/g,' ')}{t.external_reference?` · ${t.external_reference}`:''}</span></div><strong>{formatMoney(t.effective_settled,checkout.currency)}</strong>{t.change_due&&Number(t.change_due)>0&&<span>Change {formatMoney(t.change_due,checkout.currency)}</span>}</article>)}</div>:null}
    {checkout?.sale_state==='PAYMENT_IN_PROGRESS'&&Number(checkout.intent?.effective_settled)>0&&<details className="pos-fiscal-status"><summary>Return an unfinished payment</summary>
      <p>All recorded parts must return through their original methods. A different supervisor must confirm before stock reservations are released.</p>
      {!checkout.voids?.length&&checkout.can_request_void&&<><label>Reason<textarea value={voidReason} disabled={busy} onChange={e=>setVoidReason(e.target.value)}/></label><button className="pos-button" disabled={busy||!voidReason.trim()||pending.length>0} onClick={()=>command('request_void')}>Request payment void</button></>}
      {checkout.voids?.map(v=><div key={v.id}><p>{v.method} · {formatMoney(v.amount,checkout.currency)} · {v.reason}</p>{v.method==='CARD'&&<label>Terminal refund approval reference<input value={voidReferences[v.id]??''} onChange={e=>setVoidReferences(previous=>({...previous,[v.id]:e.target.value}))}/></label>}</div>)}
      {!!checkout.voids?.length&&<button className="pos-button" disabled={busy||!checkout.can_approve_void||checkout.voids.some(v=>v.own_request||v.method==='MPESA'||(v.method==='CARD'&&!voidReferences[v.id]?.trim()))} onClick={()=>command('complete_void')}>Supervisor: confirm original-method return</button>}
    </details>}
    {pendingProvider&&<button className="pos-button" disabled={busy} onClick={()=>command('query')}>Check M-PESA status</button>}
    {balance!==null&&Number(balance)===0&&!fullySettled&&<p className="pos-payment-notice">No amount to collect. Coverage or exemption status is checked separately before supply.</p>}
    {fullySettled&&<div className="pos-fiscal-status"><b>Payment settled</b>{checkout?.completion_error&&<p role="alert">{checkout.completion_error}</p>}{checkout?.sale_state==='PAYMENT_IN_PROGRESS'&&<><p>Payment is recorded. Complete the stock handover after resolving any stock or register warning.</p><button className="pos-button" disabled={busy} onClick={()=>command('finish')}>Finish paid sale</button></>}<p>Fiscal receipt: {checkout?.fiscal.status.replace(/_/g,' ')}. {checkout?.fiscal.message}</p>{checkout?.fiscal.receipt&&<dl>{Object.entries(checkout.fiscal.receipt).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>}<button className="pos-button" disabled={busy} onClick={()=>command('fiscal')}>Check / issue VSCU receipt</button></div>}
  </section>;
}
