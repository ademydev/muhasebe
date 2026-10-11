/* Static GitHub Pages storage adapter. Local Python deployments keep using /api. */
(() => {
  const KEY = 'hesap-pages-data-v1';
  const empty = () => ({version:1,accounts:[],transactions:[],debts:[],debt_payments:[],receivables:[],collections:[],categories:[],applied_imports:[]});
  const clone = value => JSON.parse(JSON.stringify(value));
  const timestamp = () => new Date().toISOString();
  const id = () => crypto.randomUUID();
  const read = () => {
    try { const saved=localStorage.getItem(KEY);if(!saved)return empty();const data=JSON.parse(saved);if(data.version!==1)throw Error('Yerel kayıt sürümü desteklenmiyor.');return data; }
    catch(error){if(error instanceof SyntaxError)throw Error('Tarayıcıdaki yerel kayıt okunamadı. Veriler korunarak işlem durduruldu.');throw error;}
  };
  const write = data => {try{localStorage.setItem(KEY,JSON.stringify(data));}catch(error){throw Error(error?.name==='QuotaExceededError'?'Tarayıcı saklama alanı dolu. Önce JSON yedeği indirin.':'Tarayıcı yerel kaydı yazılamadı.');}};
  const find = (rows,key) => {const value=rows.find(x=>x.id===key);if(!value)throw Error('Kayıt bulunamadı.');return value;};
  const account = (data,key,active=false) => {const value=find(data.accounts,key);if(active&&value.archived)throw Error('Arşivlenmiş hesaba yeni finansal kayıt eklenemez.');return value;};
  const amount = value => {let raw=String(value??'').trim().replace(/₺|TL|\s/g,'');if(raw.includes(','))raw=raw.replace(/\./g,'').replace(',','.');const n=Number(raw),cents=Math.round(n*100);if(!Number.isFinite(n)||n<0||Math.abs(n*100-cents)>1e-7)throw Error('Geçerli, negatif olmayan bir tutar girin (en fazla iki kuruş basamağı).');return cents;};
  const date = value => {const match=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);if(!match)throw Error('Geçerli bir tarih seçin.');const parsed=new Date(Number(match[1]),Number(match[2])-1,Number(match[3]));if(parsed.getFullYear()!==Number(match[1])||parsed.getMonth()!==Number(match[2])-1||parsed.getDate()!==Number(match[3]))throw Error('Geçerli bir tarih seçin.');return value;};
  const summary = (data,aid) => {
    const a=account(data,aid),tx=data.transactions.filter(x=>x.account_id===aid),debts=data.debts.filter(x=>x.account_id===aid&&!x.cancelled),payments=data.debt_payments.filter(x=>x.account_id===aid),receivables=data.receivables.filter(x=>x.account_id===aid&&!x.cancelled),collections=data.collections.filter(x=>x.account_id===aid);
    const income=tx.filter(x=>x.kind==='income').reduce((n,x)=>n+x.amount,0),expenses=tx.filter(x=>x.kind==='expense').reduce((n,x)=>n+x.amount,0),debtTotal=debts.reduce((n,x)=>n+x.amount,0),debtPaid=payments.reduce((n,x)=>n+x.amount,0),receivableTotal=receivables.reduce((n,x)=>n+x.amount,0),collected=collections.reduce((n,x)=>n+x.amount,0),realized=a.opening_balance+income-expenses,remainingDebt=Math.max(0,debtTotal-debtPaid);
    return {income,expenses,realized,debt_total:debtTotal,debt_paid:debtPaid,remaining_debt:remainingDebt,available:realized-remainingDebt,receivable_total:receivableTotal,collected,remaining_receivable:Math.max(0,receivableTotal-collected)};
  };
  const monthSummary = (data,aid,key) => {
    if(!/^\d{4}-\d{2}$/.test(key)||Number(key.slice(5))<1||Number(key.slice(5))>12)throw Error('Seçilen ay geçersiz.');
    const tx=data.transactions.filter(x=>x.account_id===aid), prevDate=new Date(Number(key.slice(0,4)),Number(key.slice(5))-2,1),prev=`${prevDate.getFullYear()}-${String(prevDate.getMonth()+1).padStart(2,'0')}`;
    const rows=tx.filter(x=>x.date.slice(0,7)===key),priorExpenses=tx.filter(x=>x.kind==='expense'&&x.date.slice(0,7)===prev).reduce((n,x)=>n+x.amount,0),income=rows.filter(x=>x.kind==='income').reduce((n,x)=>n+x.amount,0),expenses=rows.filter(x=>x.kind==='expense').reduce((n,x)=>n+x.amount,0),cats={};
    rows.filter(x=>x.kind==='expense').forEach(x=>{const name=x.category?.trim()||'Kategorisiz';cats[name]=(cats[name]||0)+x.amount;});
    const [y,m]=key.split('-').map(Number),start=`${key}-01`,paymentRows=data.debt_payments.filter(x=>x.account_id===aid&&x.date.slice(0,7)===key),collectionRows=data.collections.filter(x=>x.account_id===aid&&x.date.slice(0,7)===key),a=account(data,aid);
    const opening=a.opening_balance+tx.filter(x=>x.date<start).reduce((n,x)=>n+(x.kind==='income'?x.amount:-x.amount),0);
    return {month:key,income,expenses,net:income-expenses,opening_balance:opening,realized_balance:summary(data,aid).realized,debt_payments:paymentRows.reduce((n,x)=>n+x.amount,0),collections:collectionRows.reduce((n,x)=>n+x.amount,0),previous_month:prev,previous_expenses:priorExpenses,expense_change:expenses-priorExpenses,expense_change_percent:priorExpenses?(expenses-priorExpenses)*100/priorExpenses:null,top_categories:Object.entries(cats).sort((a,b)=>b[1]-a[1]||a[0].toLocaleLowerCase('tr').localeCompare(b[0].toLocaleLowerCase('tr'))).slice(0,3).map(([name,value])=>({name,amount:value}))};
  };
  const state = (data,url) => {
    const params=new URL(url,location.href).searchParams;let aid=params.get('account')||'';let current=data.accounts.find(x=>x.id===aid)||data.accounts.find(x=>!x.archived)||data.accounts[0]||null;aid=current?.id||'';
    const month=params.get('month')||`${new Date().getFullYear()}-${String(new Date().getMonth()+1).padStart(2,'0')}`;
    return {accounts:data.accounts,current_account:aid,summary:aid?summary(data,aid):null,monthly_summary:aid?monthSummary(data,aid,month):null,transactions:data.transactions.filter(x=>x.account_id===aid),debts:data.debts.filter(x=>x.account_id===aid&&!x.cancelled),debt_payments:data.debt_payments.filter(x=>x.account_id===aid),receivables:data.receivables.filter(x=>x.account_id===aid&&!x.cancelled),collections:data.collections.filter(x=>x.account_id===aid),categories:data.categories.filter(x=>x.account_id===aid)};
  };
  const addTransaction=(data,aid,kind,cents,day,description,category='',note='',linkedType='',linkedId='')=>{const text=String(description||'').trim();if(!text)throw Error('Açıklama boş olamaz.');data.transactions.push({id:id(),account_id:aid,date:date(day),description:text,kind,amount:cents,category:String(category||'').trim(),note:String(note||'').trim(),linked_type:linkedType,linked_id:linkedId,created_at:timestamp(),updated_at:timestamp()});};
  const mutate = (body,suppliedData,noPersist=false) => {
    const data=suppliedData||read(),action=body.action;let resultAccount='';
    if(action==='restore'){
      const incoming=body.data;if(!incoming||incoming.version!==1||!Array.isArray(incoming.accounts))throw Error('Yedek biçimi geçersiz veya desteklenmiyor.');if(body.import_id&&data.applied_imports.includes(body.import_id))return {ok:true,duplicate:true};
      const merged=clone(data),keys=['accounts','transactions','debts','debt_payments','receivables','collections','categories'];
      for(const key of keys){if(!Array.isArray(incoming[key]||[]))throw Error('Yedek içeriği bozuk.');const known=new Set(merged[key].map(x=>x.id));merged[key].push(...incoming[key].filter(x=>x?.id&&!known.has(x.id)));}
      const aids=new Set(merged.accounts.map(x=>x.id));for(const key of keys.slice(1)){const seen=new Set();for(const row of merged[key]){if(!row.id||seen.has(row.id)||!aids.has(row.account_id))throw Error('Yedekte kimlik veya hesap ilişkisi geçersiz.');seen.add(row.id);}}
      const debts=new Map(merged.debts.map(x=>[x.id,x])),recs=new Map(merged.receivables.map(x=>[x.id,x]));for(const p of merged.debt_payments)if(debts.get(p.debt_id)?.account_id!==p.account_id)throw Error('Yedekte borç ödeme ilişkisi geçersiz.');for(const c of merged.collections)if(recs.get(c.receivable_id)?.account_id!==c.account_id)throw Error('Yedekte tahsilat ilişkisi geçersiz.');
      if(body.import_id)merged.applied_imports.push(body.import_id);if(!noPersist)write(merged);else Object.assign(data,merged);return {ok:true};
    }
    if(action==='account.create'){
      const name=String(body.name||'').trim();if(!name)throw Error('Hesap adı boş olamaz.');const a={id:id(),name,description:String(body.description||'').trim(),opening_balance:amount(body.opening_balance??'0'),created_at:date(body.created_at),archived:false,created_ts:timestamp(),updated_at:timestamp()};data.accounts.push(a);resultAccount=a.id;
    } else if(action==='account.update'){
      const a=account(data,body.account_id);a.name=String(body.name||'').trim();if(!a.name)throw Error('Hesap adı boş olamaz.');a.description=String(body.description||'').trim();a.opening_balance=amount(body.opening_balance);a.updated_at=timestamp();
    } else if(action==='account.archive'||action==='account.restore'){
      const a=account(data,body.account_id);a.archived=action==='account.archive';a.updated_at=timestamp();
    } else if(action==='account.delete'){
      account(data,body.account_id);for(const key of ['transactions','debts','debt_payments','receivables','collections','categories'])data[key]=data[key].filter(x=>x.account_id!==body.account_id);data.accounts=data.accounts.filter(x=>x.id!==body.account_id);
    } else if(action==='transaction.create'){
      const aid=body.account_id;account(data,aid,true);if(!['income','expense'].includes(body.kind))throw Error('İşlem türü geçersiz.');addTransaction(data,aid,body.kind,amount(body.amount),body.date,body.description,body.category,body.note);resultAccount=aid;
    } else if(action==='transaction.update'){
      const t=find(data.transactions,body.id);if(t.account_id!==body.account_id||t.linked_type)throw Error('Bağlantılı veya başka hesaba ait işlem düzenlenemez.');account(data,body.account_id,true);if(!['income','expense'].includes(body.kind))throw Error('İşlem türü geçersiz.');t.date=date(body.date);t.description=String(body.description||'').trim();if(!t.description)throw Error('Açıklama boş olamaz.');t.kind=body.kind;t.amount=amount(body.amount);t.category=String(body.category||'').trim();t.note=String(body.note||'').trim();t.updated_at=timestamp();
    } else if(action==='transaction.delete'){
      const t=find(data.transactions,body.id);if(t.account_id!==body.account_id||t.linked_type)throw Error('Bağlantılı veya başka hesaba ait işlem silinemez.');account(data,body.account_id,true);data.transactions=data.transactions.filter(x=>x.id!==t.id);
    } else if(action==='debt.create'){
      const aid=body.account_id;account(data,aid,true);const description=String(body.description||'').trim();if(!description)throw Error('Borç açıklaması boş olamaz.');data.debts.push({id:id(),account_id:aid,description,creditor:String(body.creditor||'').trim(),date:date(body.date),due_date:body.due_date?date(body.due_date):'',amount:amount(body.amount),note:String(body.note||'').trim(),cancelled:false,created_at:timestamp(),updated_at:timestamp()});resultAccount=aid;
    } else if(action==='debt.pay'){
      const aid=body.account_id;account(data,aid,true);const d=find(data.debts,body.debt_id);if(d.account_id!==aid||d.cancelled)throw Error('Borç bu hesaba ait değil veya iptal edilmiş.');const cents=amount(body.amount),paid=data.debt_payments.filter(x=>x.debt_id===d.id).reduce((n,x)=>n+x.amount,0);if(cents<=0||cents>d.amount-paid)throw Error('Ödeme, kalan borçtan fazla olamaz ve sıfırdan büyük olmalıdır.');const pid=id(),day=date(body.date);data.debt_payments.push({id:pid,account_id:aid,debt_id:d.id,amount:cents,date:day,note:String(body.note||'').trim(),created_at:timestamp()});addTransaction(data,aid,'expense',cents,day,'Borç ödemesi · '+d.description,'Borç ödemesi',body.note,'debt_payment',pid);resultAccount=aid;
    } else if(action==='debt.cancel'){
      const d=find(data.debts,body.debt_id);if(d.account_id!==body.account_id)throw Error('Borç bu hesaba ait değil.');account(data,body.account_id,true);if(data.debt_payments.some(x=>x.debt_id===d.id))throw Error('Ödemesi olan borç iptal edilemez; ödemeleri silip tekrar deneyin.');d.cancelled=true;d.updated_at=timestamp();
    } else if(action==='debt.payment.delete'){
      const p=find(data.debt_payments,body.id);if(p.account_id!==body.account_id)throw Error('Ödeme bu hesaba ait değil.');account(data,body.account_id,true);data.transactions=data.transactions.filter(x=>x.linked_id!==p.id);data.debt_payments=data.debt_payments.filter(x=>x.id!==p.id);
    } else if(action==='receivable.create'){
      const aid=body.account_id;account(data,aid,true);const description=String(body.description||'').trim();if(!description)throw Error('Alacak açıklaması boş olamaz.');data.receivables.push({id:id(),account_id:aid,description,debtor:String(body.debtor||'').trim(),date:date(body.date),amount:amount(body.amount),note:String(body.note||'').trim(),cancelled:false,created_at:timestamp(),updated_at:timestamp()});resultAccount=aid;
    } else if(action==='receivable.collect'){
      const aid=body.account_id;account(data,aid,true);const r=find(data.receivables,body.receivable_id);if(r.account_id!==aid||r.cancelled)throw Error('Alacak bu hesaba ait değil veya iptal edilmiş.');const cents=amount(body.amount),got=data.collections.filter(x=>x.receivable_id===r.id).reduce((n,x)=>n+x.amount,0);if(cents<=0||cents>r.amount-got)throw Error('Tahsilat, kalan alacaktan fazla olamaz.');const cid=id(),day=date(body.date);data.collections.push({id:cid,account_id:aid,receivable_id:r.id,amount:cents,date:day,note:String(body.note||'').trim(),created_at:timestamp()});addTransaction(data,aid,'income',cents,day,'Alacak tahsilatı · '+r.description,'Alacak tahsilatı',body.note,'collection',cid);resultAccount=aid;
    } else if(action==='receivable.cancel'){
      const r=find(data.receivables,body.receivable_id);if(r.account_id!==body.account_id)throw Error('Alacak bu hesaba ait değil.');account(data,body.account_id,true);if(data.collections.some(x=>x.receivable_id===r.id))throw Error('Tahsilatı olan alacak iptal edilemez.');r.cancelled=true;r.updated_at=timestamp();
    } else if(action==='collection.delete'){
      const c=find(data.collections,body.id);if(c.account_id!==body.account_id)throw Error('Tahsilat bu hesaba ait değil.');account(data,body.account_id,true);data.transactions=data.transactions.filter(x=>x.linked_id!==c.id);data.collections=data.collections.filter(x=>x.id!==c.id);
    } else if(action==='category.create'){
      const aid=body.account_id;account(data,aid,true);const name=String(body.name||'').trim(),kind=body.kind;if(!name||!['income','expense'].includes(kind))throw Error('Kategori alanlarını kontrol edin.');if(data.categories.some(x=>x.account_id===aid&&x.kind===kind&&x.name.toLocaleLowerCase('tr')===name.toLocaleLowerCase('tr')))throw Error('Bu kategori zaten var.');data.categories.push({id:id(),account_id:aid,name,kind,created_at:timestamp()});resultAccount=aid;
    } else throw Error('İşlem tanınmadı.');
    if(!noPersist)write(data);return {ok:true,...(resultAccount?{account_id:resultAccount}:{})};
  };
  window.HesapBrowserStore={request:(path,body)=>{const data=read();if(body)return mutate(body);const url=new URL(path,location.href);if(url.pathname.endsWith('/api/backup'))return data;if(url.pathname.endsWith('/api/state'))return state(data,path);throw Error('İstenen adres bulunamadı.');},mutate:(body,data)=>mutate(body,data,true),projectState:(data,path)=>state(data,path)};
})();
