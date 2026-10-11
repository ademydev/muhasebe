/* Authenticated GitHub Pages data adapter. Financial state stays in memory and Supabase. */
(() => {
  const TABLE = 'hesap_user_states';
  const empty = () => ({version:1,accounts:[],transactions:[],debts:[],debt_payments:[],receivables:[],collections:[],categories:[],applied_imports:[]});
  let client = null;
  let user = null;
  let workingData = null;
  let channel = null;
  let revision = 0;
  let lastSeenRevision = null;
  const safeError = error => {
    const message = String(error?.message || 'İstek tamamlanamadı.').replace(/https?:\/\/\S+/g, '').slice(0,220);
    if (/fetch|network|failed to|load failed/i.test(message)) return 'Supabase bağlantısı kurulamadı. İnternet bağlantınızı ve Supabase URL ayarlarını kontrol edin.';
    if (/row-level security|permission denied|not allowed/i.test(message)) return 'Bu işlem için yetkiniz yok. Supabase tablo ve RLS kurulumunu kontrol edin.';
    if (/duplicate key|already exists/i.test(message)) return 'Kullanıcı verisi aynı anda başka bir oturumda oluşturuldu. Sayfayı yenileyip tekrar deneyin.';
    return message;
  };
  const fail = error => { throw Error(safeError(error)); };
  const getRow = async ownerId => {
    const {data,error}=await client.from(TABLE).select('state,revision').eq('user_id',ownerId).maybeSingle();
    if(error)fail(error);
    return data;
  };
  const loadOrCreate = async ownerId => {
    let row=await getRow(ownerId);
    if(row){revision=row.revision;return row.state;}
    const {data,error}=await client.from(TABLE).insert({user_id:ownerId,state:empty(),revision:1}).select('state,revision').single();
    if(!error){revision=data.revision;return data.state;}
    // A parallel session may have initialized the user's empty row first.
    row=await getRow(ownerId);
    if(row){revision=row.revision;return row.state;}
    fail(error);
  };
  const request = async (path, body) => {
    if(!client||!user)throw Error('Muhasebe verilerine erişmek için giriş yapın.');
    const ownerId=user.id;
    const data=await loadOrCreate(ownerId);
    if(user?.id!==ownerId)throw Error('Oturum değişti. Güvenliğiniz için işlem durduruldu; tekrar giriş yapın.');
    const url=new URL(path,location.href);
    if(!body){
      if(url.pathname.endsWith('/api/backup'))return data;
      if(url.pathname.endsWith('/api/state')){lastSeenRevision=revision;return window.HesapBrowserStore.projectState(data,path);}
      throw Error('İstenen adres bulunamadı.');
    }
    if(lastSeenRevision!==null&&lastSeenRevision!==revision)throw Error('Başka bir oturum verileri güncelledi. Son değişikliklerinizi korumak için kayıt yapılmadı; sayfayı yenileyip tekrar deneyin.');
    workingData=JSON.parse(JSON.stringify(data));
    const result=window.HesapBrowserStore.mutate(body,workingData);
    const nextRevision=revision+1;
    if(user?.id!==ownerId){workingData=null;throw Error('Oturum değişti. Güvenliğiniz için kayıt yapılmadı; tekrar giriş yapın.');}
    const {data:updated,error}=await client.from(TABLE).update({state:workingData,revision:nextRevision,updated_at:new Date().toISOString()}).eq('user_id',ownerId).eq('revision',revision).select('revision').maybeSingle();
    workingData=null;
    if(error)fail(error);
    if(!updated)throw Error('Veri başka bir açık oturumda değişti. Çakışmayı önlemek için kayıt yapılmadı; sayfayı yenileyip tekrar deneyin.');
    revision=nextRevision;lastSeenRevision=nextRevision;
    return result;
  };
  const initialize = async () => {
    if(!window.supabase?.createClient)await new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.1';script.onload=resolve;script.onerror=()=>reject(Error('Supabase istemcisi indirilemedi. İnternet bağlantınızı kontrol edin.'));document.head.append(script);
    });
    const config=window.HESAP_SUPABASE_CONFIG;
    if(!window.supabase?.createClient)throw Error('Supabase istemcisi yüklenemedi. İnternet bağlantınızı kontrol edin.');
    if(!config?.url||!config?.publishableKey)throw Error('Supabase genel yapılandırması eksik.');
    client=window.supabase.createClient(config.url,config.publishableKey,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
    return client;
  };
  const setUser = value => {
    const next=value||null;if(user?.id===next?.id)return;user=next;revision=0;lastSeenRevision=null;
    if(channel){client.removeChannel(channel);channel=null;}
    if(!user)return;
    channel=client.channel('hesap-state-'+user.id).on('postgres_changes',{event:'UPDATE',schema:'public',table:TABLE,filter:'user_id=eq.'+user.id},payload=>{
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
  window.HesapCloudStore={initialize,onAuthStateChange,signUp,signIn,signOut,sendReset,updatePassword,request,get user(){return user;}};
})();
