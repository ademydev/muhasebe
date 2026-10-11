/* Authenticated GitHub Pages data adapter. Financial state stays in memory and Supabase. */
(() => {
  const TABLE = 'hesap_user_states';
  const empty = () => ({version:1,accounts:[],transactions:[],debts:[],debt_payments:[],receivables:[],collections:[],categories:[],applied_imports:[]});
  let client = null;
  let user = null;
  let channel = null;
  let revision = 0;
  let lastSeenRevision = null;
  let cachedOwner = null;
  let cachedState = null;
  let loadPromise = null;
  const metrics = {startedAt:performance.now(),requests:[],totalRequests:0,stages:{},realtimeEvents:0};
  const now = () => performance.now();
  const recordStage = (name,start,details={}) => {metrics.stages[name]={ms:Math.round((now()-start)*10)/10,...details};};
  const recordRequest = request => {metrics.totalRequests++;metrics.requests.push(request);if(metrics.requests.length>200)metrics.requests.shift();};
  const safeError = error => {
    const message = String(error?.message || 'İstek tamamlanamadı.').replace(/https?:\/\/\S+/g, '').slice(0,220);
    if (/fetch|network|failed to|load failed/i.test(message)) return 'Supabase bağlantısı kurulamadı. İnternet bağlantınızı ve Supabase URL ayarlarını kontrol edin.';
    if (/row-level security|permission denied|not allowed/i.test(message)) return 'Bu işlem için yetkiniz yok. Supabase tablo ve RLS kurulumunu kontrol edin.';
    if (/duplicate key|already exists/i.test(message)) return 'Kullanıcı verisi aynı anda başka bir oturumda oluşturuldu. Sayfayı yenileyip tekrar deneyin.';
    return message;
  };
  const fail = error => { throw Error(safeError(error)); };
  const measuredFetch = async (input,init) => {
    const started=now();
    try {
      const response=await fetch(input,init);
      const url=new URL(typeof input==='string'?input:input.url,location.href);
      const path=url.pathname;
      const service=path.includes('/auth/')?'auth':path.includes('/rest/v1/')?'database':path.includes('/realtime/')?'realtime':'other';
      let payloadBytes=Number(init?.body?.length||0);
      if(!payloadBytes&&init?.body&&typeof init.body!=='string')payloadBytes=0;
      recordRequest({service,method:init?.method||'GET',status:response.status,ms:Math.round((now()-started)*10)/10,payloadBytes});
      return response;
    } catch(error) {
      recordRequest({service:'network',method:init?.method||'GET',status:0,ms:Math.round((now()-started)*10)/10,payloadBytes:0});
      throw error;
    }
  };
  const getRow = async ownerId => {
    const {data,error}=await client.from(TABLE).select('state,revision').eq('user_id',ownerId).maybeSingle();
    if(error)fail(error);
    return data;
  };
  const loadOrCreate = async (ownerId,force=false) => {
    if(!force&&cachedOwner===ownerId&&cachedState)return cachedState;
    if(!force&&loadPromise?.ownerId===ownerId)return loadPromise.promise;
    const promise=(async()=>{
      const started=now();
      let row=await getRow(ownerId);
      if(row){revision=row.revision;cachedOwner=ownerId;cachedState=row.state;recordStage('cloudRead',started,{payloadBytes:JSON.stringify(row.state).length,created:false});return row.state;}
      const {data,error}=await client.from(TABLE).insert({user_id:ownerId,state:empty(),revision:1}).select('state,revision').single();
      if(!error){revision=data.revision;cachedOwner=ownerId;cachedState=data.state;recordStage('cloudRead',started,{payloadBytes:JSON.stringify(data.state).length,created:true});return data.state;}
      // A parallel session may have initialized the user's empty row first.
      row=await getRow(ownerId);
      if(row){revision=row.revision;cachedOwner=ownerId;cachedState=row.state;recordStage('cloudRead',started,{payloadBytes:JSON.stringify(row.state).length,created:false,concurrentInitialization:true});return row.state;}
      fail(error);
    })();
    loadPromise={ownerId,promise};
    try{return await promise;}finally{if(loadPromise?.promise===promise)loadPromise=null;}
  };
  const request = async (path, body, options={}) => {
    if(!client||!user)throw Error('Muhasebe verilerine erişmek için giriş yapın.');
    const ownerId=user.id;
    const data=await loadOrCreate(ownerId,options.force===true);
    if(user?.id!==ownerId)throw Error('Oturum değişti. Güvenliğiniz için işlem durduruldu; tekrar giriş yapın.');
    const url=new URL(path,location.href);
    if(!body){
      if(url.pathname.endsWith('/api/backup'))return data;
      if(url.pathname.endsWith('/api/state')){lastSeenRevision=revision;const started=now();const projected=window.HesapBrowserStore.projectState(data,path);recordStage('projection',started,{payloadBytes:JSON.stringify(projected).length});return projected;}
      throw Error('İstenen adres bulunamadı.');
    }
    if(lastSeenRevision!==null&&lastSeenRevision!==revision)throw Error('Başka bir oturum verileri güncelledi. Son değişikliklerinizi korumak için kayıt yapılmadı; sayfayı yenileyip tekrar deneyin.');
    const started=now();
    const workingData=JSON.parse(JSON.stringify(data));
    const result=window.HesapBrowserStore.mutate(body,workingData);
    recordStage('mutation',started,{payloadBytes:JSON.stringify(workingData).length});
    const nextRevision=revision+1;
    if(user?.id!==ownerId)throw Error('Oturum değişti. Güvenliğiniz için kayıt yapılmadı; tekrar giriş yapın.');
    const saveStarted=now();
    const {data:updated,error}=await client.from(TABLE).update({state:workingData,revision:nextRevision,updated_at:new Date().toISOString()}).eq('user_id',ownerId).eq('revision',revision).select('revision').maybeSingle();
    recordStage('cloudWrite',saveStarted,{payloadBytes:JSON.stringify(workingData).length});
    if(error)fail(error);
    if(!updated)throw Error('Veri başka bir açık oturumda değişti. Çakışmayı önlemek için kayıt yapılmadı; sayfayı yenileyip tekrar deneyin.');
    revision=nextRevision;lastSeenRevision=nextRevision;cachedOwner=ownerId;cachedState=workingData;
    return result;
  };
  const initialize = async () => {
    const initStarted=now();
    if(!window.supabase?.createClient)await new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.1';script.onload=resolve;script.onerror=()=>reject(Error('Supabase istemcisi indirilemedi. İnternet bağlantınızı kontrol edin.'));document.head.append(script);
    });
    const config=window.HESAP_SUPABASE_CONFIG;
    if(!window.supabase?.createClient)throw Error('Supabase istemcisi yüklenemedi. İnternet bağlantınızı kontrol edin.');
    if(!config?.url||!config?.publishableKey)throw Error('Supabase genel yapılandırması eksik.');
    client=window.supabase.createClient(config.url,config.publishableKey,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true},global:{fetch:measuredFetch}});
    recordStage('clientInitialize',initStarted);
    return client;
  };
  const setUser = value => {
    const next=value||null;if(user?.id===next?.id)return;user=next;revision=0;lastSeenRevision=null;cachedOwner=null;cachedState=null;loadPromise=null;
    if(channel){client.removeChannel(channel);channel=null;}
    if(!user)return;
    channel=client.channel('hesap-state-'+user.id).on('postgres_changes',{event:'UPDATE',schema:'public',table:TABLE,filter:'user_id=eq.'+user.id},payload=>{
      metrics.realtimeEvents++;
      if(payload.new?.revision>revision)window.dispatchEvent(new CustomEvent('hesap-cloud-updated'));
    }).subscribe();
  };
  const signUp = async (email,password) => {
    const {data,error}=await client.auth.signUp({email,password,options:{emailRedirectTo:location.origin+location.pathname}});
    if(error)fail(error);
    return {session:!!data.session};
  };
  const signIn = async (email,password) => {const {data,error}=await client.auth.signInWithPassword({email,password});if(error)fail(error);return data;};
  const signOut = async () => {const {error}=await client.auth.signOut();if(error)fail(error);};
  const sendReset = async email => {const {error}=await client.auth.resetPasswordForEmail(email,{redirectTo:location.origin+location.pathname});if(error)fail(error);};
  const updatePassword = async password => {const {error}=await client.auth.updateUser({password});if(error)fail(error);};
  const onAuthStateChange = callback => client.auth.onAuthStateChange((event,session)=>{
    setUser(session?.user||null);
    callback(event,session);
  });
  const report = () => ({...JSON.parse(JSON.stringify(metrics)),elapsedMs:Math.round((now()-metrics.startedAt)*10)/10,requestCount:metrics.totalRequests,requestSamples:metrics.requests.length,note:'En fazla son 200 isteğin servis türü, yöntemi, yanıt kodu, süresi ve yaklaşık yük boyutu tutulur; kullanıcı kimliği ve finansal içerik rapora eklenmez.'});
  window.HesapPerf={report};
  window.HesapCloudStore={initialize,onAuthStateChange,signUp,signIn,signOut,sendReset,updatePassword,request,get user(){return user;}};
})();
