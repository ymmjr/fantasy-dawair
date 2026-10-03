# -*- coding: utf-8 -*-
import os, json, time, secrets, hashlib, sqlite3, threading, mimetypes, urllib.parse, http.cookies, re, base64, binascii
from pathlib import Path
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet, InvalidToken

ROOT=Path(__file__).resolve().parent
PUBLIC=ROOT/"public"; DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
PORT=int(os.getenv("PORT","3000")); HOST=os.getenv("HOST","0.0.0.0")
DATABASE_URL=os.getenv("DATABASE_URL","").strip()
PG=DATABASE_URL.startswith(("postgres://","postgresql://"))
LOCK=threading.RLock(); SESS={}; SESSION_TTL=7*24*3600
CODE_KEY=os.getenv("PARTICIPANT_CODE_KEY","").strip()
CODE_CIPHER=Fernet(CODE_KEY.encode()) if CODE_KEY else None

if PG:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn=psycopg2.connect(DATABASE_URL)
    conn.autocommit=True
else:
    conn=sqlite3.connect(DATA/"fantasy.db",check_same_thread=False)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

def sql(q): return q.replace("?","%s") if PG else q
def execq(q,a=()):
    c=conn.cursor(cursor_factory=RealDictCursor) if PG else conn.cursor()
    c.execute(sql(q),a); return c
def rows(q,a=()): return [dict(x) for x in execq(q,a).fetchall()]
def row(q,a=()):
    x=execq(q,a).fetchone(); return dict(x) if x else None
def val(q,a=(),default=0):
    x=execq(q,a).fetchone()
    if not x:return default
    if isinstance(x,dict):return next(iter(x.values()))
    return x[0]
def insert_id(q,a=()):
    if PG:
        c=execq(q+" RETURNING id",a); return c.fetchone()["id"]
    c=execq(q,a); conn.commit(); return c.lastrowid
def now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def i(v,d=0):
    try:return int(v)
    except:return d
def h(secret,salt):
    return hashlib.scrypt(str(secret).encode(),salt=str(salt).encode(),n=16384,r=8,p=1,dklen=32).hex()
def enc_code(v):
    if not CODE_CIPHER: raise RuntimeError("PARTICIPANT_CODE_KEY is not configured")
    return CODE_CIPHER.encrypt(str(v).encode()).decode()
def dec_code(v):
    if not v or not CODE_CIPHER:return None
    try:return CODE_CIPHER.decrypt(str(v).encode()).decode()
    except InvalidToken:return None
def norm_username(v): return re.sub(r"\s+"," ",str(v or "").strip()).lower()
def valid_username(v): return 3<=len(v)<=32 and bool(re.fullmatch(r"[\w.-]+(?: [\w.-]+)*",v,re.UNICODE))
def clean_profile_image(v):
    if v in (None,""):return None
    v=str(v).strip()
    m=re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\r\n]+)",v)
    if not m:raise ValueError("صيغة الصورة غير مدعومة")
    try:data=base64.b64decode(m.group(2),validate=True)
    except (binascii.Error,ValueError):raise ValueError("بيانات الصورة غير صالحة")
    if len(data)>550_000:raise ValueError("حجم الصورة كبير؛ الحد الأقصى 550KB بعد المعالجة")
    if len(data)<100:raise ValueError("الصورة غير صالحة")
    return "data:image/"+m.group(1)+";base64,"+base64.b64encode(data).decode()
def has_col(table,col):
    if PG:return bool(row("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=? AND column_name=?",(table,col)))
    return any(x["name"]==col for x in rows(f"PRAGMA table_info({table})"))


def player_account_username(name):
    parts=[x for x in re.split(r"\s+",str(name or "").strip()) if x]
    if not parts:return ""
    if len(parts)>=3 and parts[-2:]==["شمس","الدين"]:
        out=f"{parts[0]} شمس الدين"
    else:
        out=parts[0] if len(parts)==1 else f"{parts[0]} {parts[-1]}"
    out=re.sub(r"[\u064B-\u065F\u0670\u0640]","",out)
    return norm_username(out)

def english_first_name(name):
    parts=[x for x in re.split(r"\s+",str(name or "").strip()) if x]
    first=parts[0] if parts else "Player"
    if re.fullmatch(r"[A-Za-z][A-Za-z'.-]*",first):
        return first[:1].upper()+first[1:].lower()
    ar=re.sub(r"[\u064B-\u065F\u0670\u0640]","",first)
    ar=ar.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    known={
      "يوسف":"Yousef","محمد":"Mohammed","محمود":"Mahmoud","احمد":"Ahmed","حمد":"Hamad","راكان":"Rakan","داود":"Dawood","مساعد":"Musaed","رشود":"Rshood","سالم":"Salem",
      "خالد":"Khaled","فهد":"Fahad","سعود":"Saud","ناصر":"Nasser","بدر":"Bader",
      "سلمان":"Salman","عمر":"Omar","علي":"Ali","حسن":"Hasan","حسين":"Hussain",
      "مشعل":"Meshal","فيصل":"Faisal","راشد":"Rashid","صالح":"Saleh","ابراهيم":"Ibrahim",
      "اسماعيل":"Ismail","اسحاق":"Ishaq","ايوب":"Ayoub","ادم":"Adam","يحيى":"Yahya",
      "زكريا":"Zakariya","طارق":"Tariq","طلال":"Talal","تركي":"Turki","جاسم":"Jassim",
      "جابر":"Jaber","حبيب":"Habib","حمود":"Hammoud","حمدان":"Hamdan","حمدي":"Hamdi",
      "سعد":"Saad","سعيد":"Saeed","سيف":"Saif","سلطان":"Sultan","عبدالله":"Abdullah",
      "عبدالرحمن":"Abdulrahman","عبدالعزيز":"Abdulaziz","عبدالمحسن":"Abdulmohsen",
      "عبداللطيف":"Abdullatif","عبدالملك":"Abdulmalik","عبدالوهاب":"Abdulwahab",
      "عبدالقادر":"Abdulqader","عبدالكريم":"Abdulkarim","عبدالهادي":"Abdulhadi",
      "عبدالرحيم":"Abdulrahim","عبدالناصر":"Abdulnasser","عبدالاله":"Abdulilah",
      "عبدالاله":"Abdulilah","عبدالمجيد":"Abdulmajeed","عبدالحميد":"Abdulhameed",
      "عبدالصمد":"Abdulsamad","عبدالواحد":"Abdulwahid","عبدالمنعم":"Abdulmunim",
      "وليد":"Waleed","ماجد":"Majed","مازن":"Mazen","معاذ":"Muath","مرزوق":"Marzouq",
      "مبارك":"Mubarak","منصور":"Mansour","نايف":"Nayef","نواف":"Nawaf","هشام":"Hisham",
      "هيثم":"Haitham","يزيد":"Yazeed","ياسر":"Yasser","يعقوب":"Yaqoub","امين":"Ameen",
      "انس":"Anas","اسامة":"Osama","اكرم":"Akram","ايمن":"Ayman","بشار":"Bashar",
      "بسام":"Bassam","ثامر":"Thamer","حازم":"Hazem","حاتم":"Hatem","ربيع":"Rabee",
      "زياد":"Ziyad","سامر":"Samer","سامي":"Sami","شهاب":"Shehab","صقر":"Saqr",
      "ضياء":"Diaa","عادل":"Adel","عارف":"Aref","عامر":"Amer","عباس":"Abbas",
      "عثمان":"Othman","عدنان":"Adnan","عيسى":"Essa","غازي":"Ghazi","فارس":"Fares",
      "فواز":"Fawaz","قاسم":"Qasim","كريم":"Kareem","لطفي":"Lotfi","لؤي":"Loay",
      "مصعب":"Musab","مهدي":"Mahdi","مهند":"Muhannad","موسى":"Musa","نبيل":"Nabil"
    }
    if ar in known:return known[ar]
    mp={"ا":"a","ب":"b","ت":"t","ث":"th","ج":"j","ح":"h","خ":"kh","د":"d","ذ":"dh","ر":"r","ز":"z","س":"s","ش":"sh","ص":"s","ض":"d","ط":"t","ظ":"z","ع":"a","غ":"gh","ف":"f","ق":"q","ك":"k","ل":"l","م":"m","ن":"n","ه":"h","و":"w","ي":"y","ى":"a","ة":"h","ء":"","ئ":"y","ؤ":"w"}
    s="".join(mp.get(ch,ch) for ch in ar)
    s=re.sub(r"[^A-Za-z0-9]","",s) or "Player"
    return s[:1].upper()+s[1:].lower()

def ensure_player_accounts_v6():
    if val("SELECT COUNT(*) FROM schema_migrations WHERE version=6"):return
    made=updated=linked=skipped=0
    details=[]
    for p in rows("SELECT id,name,participant_id FROM players WHERE active=1 ORDER BY id"):
        username=player_account_username(p["name"])
        code=english_first_name(p["name"])+"123"
        if not valid_username(username):
            skipped+=1;details.append({"player_id":p["id"],"name":p["name"],"status":"invalid_username"});continue
        cipher=enc_code(code) if CODE_CIPHER else None
        uid=p.get("participant_id")
        if uid:
            other=row("SELECT id FROM participants WHERE username=? AND id<>?",(username,uid))
            if other:
                skipped+=1;details.append({"player_id":p["id"],"name":p["name"],"status":"username_conflict"});continue
            execq("UPDATE participants SET name=?,username=?,code_hash=?,code_hint=?,code_ciphertext=?,active=1 WHERE id=?",(p["name"],username,h(code.upper(),"dawair-participant-v1"),code[-3:].upper(),cipher,uid))
            updated+=1
        else:
            existing=row("SELECT id FROM participants WHERE username=?",(username,))
            if existing:
                used=row("SELECT id FROM players WHERE participant_id=? AND id<>?",(existing["id"],p["id"]))
                if used:
                    skipped+=1;details.append({"player_id":p["id"],"name":p["name"],"status":"username_conflict"});continue
                uid=existing["id"]
                execq("UPDATE participants SET name=?,code_hash=?,code_hint=?,code_ciphertext=?,active=1 WHERE id=?",(p["name"],h(code.upper(),"dawair-participant-v1"),code[-3:].upper(),cipher,uid))
                execq("UPDATE players SET participant_id=? WHERE id=?",(uid,p["id"]))
                linked+=1
            else:
                uid=insert_id("INSERT INTO participants(name,username,code_hash,code_hint,code_ciphertext,active,created_at) VALUES(?,?,?,?,?,1,?)",(p["name"],username,h(code.upper(),"dawair-participant-v1"),code[-3:].upper(),cipher,now()))
                execq("UPDATE players SET participant_id=? WHERE id=?",(uid,p["id"]))
                made+=1
        details.append({"player_id":p["id"],"name":p["name"],"username":username,"status":"ok"})
    execq("INSERT INTO schema_migrations(version,applied_at) VALUES(6,?) ON CONFLICT(version) DO NOTHING",(now(),))
    if not PG:conn.commit()
    print("PLAYER_ACCOUNTS_V6",json.dumps({"created":made,"updated":updated,"linked_existing":linked,"skipped":skipped,"details":details},ensure_ascii=False))


def snapshot_round(rid,force=False):
    if force:execq("DELETE FROM round_players WHERE round_id=?",(rid,))
    if val("SELECT COUNT(*) FROM round_players WHERE round_id=?",(rid,)):return
    for p in rows("SELECT id,name,group_no FROM players WHERE active=1 ORDER BY group_no,name"):
        execq("INSERT INTO round_players(round_id,player_id,name,group_no) VALUES(?,?,?,?) ON CONFLICT(round_id,player_id) DO NOTHING",(rid,p["id"],p["name"],p["group_no"]))
    if not PG:conn.commit()

def ensure_next_round(after_number):
    nxt=row("SELECT * FROM rounds WHERE number>? ORDER BY number ASC LIMIT 1",(after_number,))
    if nxt:return nxt
    num=after_number+1
    rid=insert_id("INSERT INTO rounds(number,name,status,created_at) VALUES(?,?,?,?)",(num,f"الجولة {num}","draft",now()))
    return row("SELECT * FROM rounds WHERE id=?",(rid,))

def competition_round():
    return row("SELECT * FROM rounds WHERE status='open' ORDER BY number DESC LIMIT 1") or row("SELECT * FROM rounds WHERE status IN ('locked','scored') ORDER BY number DESC LIMIT 1") or row("SELECT * FROM rounds ORDER BY number DESC LIMIT 1")

def lineup_target_round():
    op=row("SELECT * FROM rounds WHERE status='open' ORDER BY number DESC LIMIT 1")
    if op:return op
    cur=row("SELECT * FROM rounds WHERE status IN ('locked','scored') ORDER BY number DESC LIMIT 1")
    if cur:
        nxt=row("SELECT * FROM rounds WHERE number>? AND status='draft' ORDER BY number ASC LIMIT 1",(cur["number"],))
        return nxt or ensure_next_round(cur["number"])
    return row("SELECT * FROM rounds WHERE status='draft' ORDER BY number ASC LIMIT 1") or row("SELECT * FROM rounds ORDER BY number DESC LIMIT 1")

def player_pool_for_round(r):
    if not r:return []
    if r["status"]=="draft":
        return rows("SELECT p.id,p.name,p.group_no,u.profile_image,COALESCE((SELECT SUM(e.raw_points) FROM events e WHERE e.player_id=p.id),0) total_points FROM players p LEFT JOIN participants u ON u.id=p.participant_id WHERE p.active=1 ORDER BY p.group_no,p.name")
    snapshot_round(r["id"])
    return rows("SELECT rp.player_id id,rp.name,rp.group_no,u.profile_image,COALESCE((SELECT SUM(e.raw_points) FROM events e WHERE e.player_id=rp.player_id),0) total_points FROM round_players rp LEFT JOIN players p ON p.id=rp.player_id LEFT JOIN participants u ON u.id=p.participant_id WHERE rp.round_id=? ORDER BY rp.group_no,rp.name",(r["id"],))

def init():
    ID="BIGSERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    schema=f"""
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admins(id {ID},username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,salt TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS participants(id {ID},name TEXT NOT NULL,code_hash TEXT NOT NULL,code_hint TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS players(id {ID},name TEXT NOT NULL,group_no INTEGER NOT NULL CHECK(group_no BETWEEN 1 AND 4),active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rounds(id {ID},number INTEGER UNIQUE NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',lock_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS round_players(round_id BIGINT NOT NULL,player_id BIGINT NOT NULL,name TEXT NOT NULL,group_no INTEGER NOT NULL CHECK(group_no BETWEEN 1 AND 4),PRIMARY KEY(round_id,player_id));
CREATE TABLE IF NOT EXISTS lineups(id {ID},participant_id BIGINT NOT NULL,round_id BIGINT NOT NULL,captain_player_id BIGINT NOT NULL,vice_player_id BIGINT NOT NULL,chip TEXT,submitted_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(participant_id,round_id));
CREATE TABLE IF NOT EXISTS lineup_players(id {ID},lineup_id BIGINT NOT NULL,player_id BIGINT NOT NULL,role TEXT NOT NULL,bench_order INTEGER NOT NULL DEFAULT 0,UNIQUE(lineup_id,player_id));
CREATE TABLE IF NOT EXISTS events(id {ID},round_id BIGINT NOT NULL,player_id BIGINT NOT NULL,goals INTEGER NOT NULL DEFAULT 0,wins INTEGER NOT NULL DEFAULT 0,hattricks INTEGER NOT NULL DEFAULT 0,attendance INTEGER NOT NULL DEFAULT 0,best_player INTEGER NOT NULL DEFAULT 0,yellow INTEGER NOT NULL DEFAULT 0,red INTEGER NOT NULL DEFAULT 0,no_shoes INTEGER NOT NULL DEFAULT 0,own_goals INTEGER NOT NULL DEFAULT 0,raw_points INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,UNIQUE(round_id,player_id));
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
"""
    with LOCK:
        if PG:
            c=conn.cursor()
            for s in schema.split(";"):
                if s.strip(): c.execute(s)
        else: conn.executescript(schema)
        # v2: participant usernames + one-to-one participant/player linking.
        if not has_col("participants","username"): execq("ALTER TABLE participants ADD COLUMN username TEXT")
        if not has_col("participants","code_ciphertext"): execq("ALTER TABLE participants ADD COLUMN code_ciphertext TEXT")
        if not has_col("participants","profile_image"): execq("ALTER TABLE participants ADD COLUMN profile_image TEXT")
        if not has_col("participants","is_admin"): execq("ALTER TABLE participants ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if not has_col("players","participant_id"): execq("ALTER TABLE players ADD COLUMN participant_id BIGINT")
        for u in rows("SELECT id FROM participants WHERE username IS NULL OR TRIM(username)='' ORDER BY id"):
            execq("UPDATE participants SET username=? WHERE id=?",(f"user{u['id']}",u["id"]))
        if PG: execq("ALTER TABLE participants DROP CONSTRAINT IF EXISTS participants_code_hash_key")
        execq("CREATE UNIQUE INDEX IF NOT EXISTS idx_participants_username ON participants(username)")
        execq("CREATE UNIQUE INDEX IF NOT EXISTS idx_players_participant_id ON players(participant_id) WHERE participant_id IS NOT NULL")
        defaults={
          "site_name":"فانتسي دوائر","captain_multiplier":"2","free_transfers":"2",
          "points_goal":"3","points_win":"5","points_hattrick":"3","points_attendance":"3",
          "points_best_player":"8","points_yellow":"-2","points_red":"-5","points_no_shoes":"-3","points_own_goal":"-2",
          "rules_note":"اختر 8 لاعبين: 2 من كل مجموعة، 6 أساسيين و2 احتياط. الكبتن والنائب من الأساسيين فقط. كل طاقة تستخدم مرة واحدة."
        }
        for k,v in defaults.items(): execq("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",(k,v))
        execq("INSERT INTO schema_migrations(version,applied_at) VALUES(1,?) ON CONFLICT(version) DO NOTHING",(now(),))
        execq("INSERT INTO schema_migrations(version,applied_at) VALUES(2,?) ON CONFLICT(version) DO NOTHING",(now(),))
        execq("INSERT INTO schema_migrations(version,applied_at) VALUES(3,?) ON CONFLICT(version) DO NOTHING",(now(),))
        execq("INSERT INTO schema_migrations(version,applied_at) VALUES(4,?) ON CONFLICT(version) DO NOTHING",(now(),))
        execq("INSERT INTO schema_migrations(version,applied_at) VALUES(7,?) ON CONFLICT(version) DO NOTHING",(now(),))
        execq("INSERT INTO schema_migrations(version,applied_at) VALUES(8,?) ON CONFLICT(version) DO NOTHING",(now(),))
        ensure_player_accounts_v6()
        if val("SELECT COUNT(*) FROM admins")==0:
            user=os.getenv("ADMIN_USERNAME","admin")
            pw=os.getenv("ADMIN_PASSWORD","").strip() or secrets.token_urlsafe(16)
            salt=secrets.token_hex(16)
            insert_id("INSERT INTO admins(username,password_hash,salt,created_at) VALUES(?,?,?,?)",(user,h(pw,salt),salt,now()))
            if not os.getenv("ADMIN_PASSWORD"): print("INITIAL ADMIN PASSWORD:",pw)
        if val("SELECT COUNT(*) FROM rounds")==0:
            insert_id("INSERT INTO rounds(number,name,status,created_at) VALUES(1,'الجولة 1','open',?)",(now(),))
        for rr in rows("SELECT id FROM rounds WHERE status IN ('open','locked','scored') ORDER BY number"):
            snapshot_round(rr["id"])
        if not PG: conn.commit()
init()

def settings():
    out={}
    for r in rows("SELECT key,value FROM settings"):
        v=r["value"]
        try:out[r["key"]]=int(v)
        except:out[r["key"]]=v
    return out

def raw(e,s=None):
    s=s or settings()
    return i(e.get("goals"))*s["points_goal"]+i(e.get("wins"))*s["points_win"]+i(e.get("hattricks"))*s["points_hattrick"]+(s["points_attendance"] if i(e.get("attendance")) else 0)+i(e.get("best_player"))*s["points_best_player"]+i(e.get("yellow"))*s["points_yellow"]+i(e.get("red"))*s["points_red"]+i(e.get("no_shoes"))*s["points_no_shoes"]+i(e.get("own_goals"))*s["points_own_goal"]

def lineup(pid,rid):
    l=row("SELECT * FROM lineups WHERE participant_id=? AND round_id=?",(pid,rid))
    if l:l["players"]=rows("SELECT lp.*,COALESCE(rp.name,p.name) name,COALESCE(rp.group_no,p.group_no) group_no,u.profile_image FROM lineup_players lp JOIN players p ON p.id=lp.player_id LEFT JOIN round_players rp ON rp.round_id=? AND rp.player_id=p.id LEFT JOIN participants u ON u.id=p.participant_id WHERE lp.lineup_id=? ORDER BY CASE lp.role WHEN 'starter' THEN 0 ELSE 1 END,lp.bench_order",(rid,l["id"]))
    return l

def used_chips(pid,exclude=0):
    q="SELECT chip FROM lineups WHERE participant_id=? AND chip IS NOT NULL"; a=[pid]
    if exclude:q+=" AND round_id<>?";a.append(exclude)
    return [x["chip"] for x in rows(q,tuple(a))]

def score(pid,rid):
    l=lineup(pid,rid)
    if not l:return 0
    ev={x["player_id"]:x for x in rows("SELECT player_id,raw_points,attendance FROM events WHERE round_id=?",(rid,))}
    total=0
    for p in l["players"]:
        if p["role"]=="starter" or l.get("chip")=="bench_boost": total+=ev.get(p["player_id"],{}).get("raw_points",0)
    s=settings(); cap=ev.get(l["captain_player_id"],{})
    cid=l["captain_player_id"] if cap.get("attendance") else l["vice_player_id"]
    ce=ev.get(cid,{})
    if ce.get("attendance"):
        mult=3 if (cid==l["captain_player_id"] and l.get("chip")=="triple_captain") else s["captain_multiplier"]
        total+=ce.get("raw_points",0)*(mult-1)
    return total

def leaderboard(rid=0):
    rs=rows("SELECT id FROM rounds WHERE status IN ('open','locked','scored') ORDER BY number")
    out=[]
    for p in rows("SELECT id,name,profile_image FROM participants WHERE active=1 ORDER BY name"):
        total=sum(score(p["id"],r["id"]) for r in rs)
        rp=score(p["id"],rid) if rid else None
        out.append({"id":p["id"],"name":p["name"],"profile_image":p.get("profile_image"),"total_points":total,"round_points":rp})
    out.sort(key=lambda x:(-(x["round_points"] if rid else x["total_points"]),-x["total_points"],x["name"]))
    for n,x in enumerate(out,1):x["rank"]=n
    return out

class H(BaseHTTPRequestHandler):
    def log_message(self,f,*a): print("[WEB]",f%a)
    def body(self):
        n=min(i(self.headers.get("Content-Length")),2_000_000)
        return json.loads(self.rfile.read(n).decode()) if n else {}
    def cookies(self):
        c=http.cookies.SimpleCookie();c.load(self.headers.get("Cookie",""));return {k:v.value for k,v in c.items()}
    def sess(self):
        t=self.cookies().get("sid"); x=SESS.get(t)
        if not x:return None
        if time.time()-x["t"]>SESSION_TTL:SESS.pop(t,None);return None
        if x.get("participant_id"):
            u=row("SELECT name,username,active,is_admin FROM participants WHERE id=?",(x["participant_id"],))
            if not u or not u.get("active"):SESS.pop(t,None);return None
            x["name"]=u["name"];x["username"]=u.get("username");x["is_admin"]=bool(u.get("is_admin"))
        x["t"]=time.time();return x
    def new_session(self,x):
        t=secrets.token_hex(24); SESS[t]={**x,"t":time.time()}; return t
    def sendj(self,status,obj,cookie=None):
        b=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff");self.send_header("X-Frame-Options","DENY")
        if cookie:self.send_header("Set-Cookie",cookie)
        self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def static(self,p):
        rel="index.html" if p=="/" else p.lstrip("/"); f=(PUBLIC/rel).resolve()
        if PUBLIC.resolve() not in f.parents and f!=PUBLIC.resolve():return self.sendj(403,{"error":"forbidden"})
        if not f.exists() or f.is_dir():f=PUBLIC/"index.html"
        b=f.read_bytes();ct=mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        self.send_response(200);self.send_header("Content-Type",ct);self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):self.route("GET")
    def do_POST(self):self.route("POST")
    def do_PUT(self):self.route("PUT")
    def do_DELETE(self):self.route("DELETE")
    def route(self,m):
        u=urllib.parse.urlsplit(self.path);p=u.path;q=urllib.parse.parse_qs(u.query)
        try:
            if p=="/health":return self.sendj(200,{"ok":True,"database":"postgres" if PG else "sqlite"})
            if not p.startswith("/api/"):return self.static(p)
            with LOCK:return self.api(m,p,q)
        except Exception as e:
            import traceback;traceback.print_exc();return self.sendj(500,{"error":"حدث خطأ داخلي","detail":str(e)})
    def auth(self,role=None):
        s=self.sess()
        if not s:self.sendj(401,{"error":"يلزم تسجيل الدخول"});return None
        if role=="admin" and not s.get("is_admin"):self.sendj(403,{"error":"غير مصرح"});return None
        if role=="participant" and not s.get("participant_id"):self.sendj(403,{"error":"هذا الحساب غير مرتبط بمشارك"});return None
        return s
    def api(self,m,p,q):
        if m=="POST" and p in ("/api/login","/api/login/participant","/api/login/admin"):
            b=self.body();un=norm_username(b.get("username",""));secret=str(b.get("password",b.get("code",""))).strip()
            if un and secret:
                code=h(secret.upper(),"dawair-participant-v1")
                u=row("SELECT id,name,username,code_hash,code_ciphertext,is_admin FROM participants WHERE username=? AND active=1",(un,))
                if u and code==u["code_hash"]:
                    if not u.get("code_ciphertext") and CODE_CIPHER:
                        execq("UPDATE participants SET code_ciphertext=? WHERE id=?",(enc_code(secret),u["id"]))
                        if not PG:conn.commit()
                    t=self.new_session({"role":"participant","id":u["id"],"participant_id":u["id"],"name":u["name"],"username":u.get("username"),"is_admin":bool(u.get("is_admin")),"legacy_admin":False})
                    return self.sendj(200,{"ok":True},f"sid={t}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800")
                ad=row("SELECT * FROM admins WHERE username=?",(str(b.get("username","")).strip(),))
                if ad and h(secret,ad["salt"])==ad["password_hash"]:
                    t=self.new_session({"role":"admin","id":ad["id"],"participant_id":None,"name":ad["username"],"username":ad["username"],"is_admin":True,"legacy_admin":True})
                    return self.sendj(200,{"ok":True},f"sid={t}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800")
            return self.sendj(401,{"error":"اسم المستخدم أو كلمة المرور غير صحيحة"})
        if m=="POST" and p=="/api/logout":SESS.pop(self.cookies().get("sid"),None);return self.sendj(200,{"ok":True},"sid=; Path=/; Max-Age=0")
        if m=="GET" and p=="/api/me":
            s=self.sess();return self.sendj(200,{"authenticated":False} if not s else {"authenticated":True,"role":s["role"],"id":s["id"],"participant_id":s.get("participant_id"),"has_participant":bool(s.get("participant_id")),"is_admin":bool(s.get("is_admin")),"legacy_admin":bool(s.get("legacy_admin")),"name":s["name"],"username":s.get("username")})
        a=self.auth()
        if not a:return
        if m=="GET" and p=="/api/bootstrap":
            cur=competition_round();target=lineup_target_round();rr=rows("SELECT * FROM rounds ORDER BY number DESC")
            out={"settings":settings(),"players":player_pool_for_round(target),"rounds":rr,"current_round":cur,"lineup_round":target,"editing_next_round":bool(target and cur and target["id"]!=cur["id"])}
            if a.get("participant_id"):
                pid=a["participant_id"];out["lineup"]=lineup(pid,target["id"]) if target else None;out["used_chips"]=used_chips(pid,target["id"] if target else 0);out["leaderboard"]=leaderboard(cur["id"] if cur and cur["status"]!="draft" else 0)
            return self.sendj(200,out)
        if m=="GET" and p=="/api/leaderboard":return self.sendj(200,leaderboard(i(q.get("round_id",["0"])[0])))
        parts=p.strip("/").split("/")
        if len(parts)==3 and parts[:2]==["api","lineup"] and a.get("participant_id"):
            rid=i(parts[2]); r=row("SELECT * FROM rounds WHERE id=?",(rid,))
            if m=="GET":return self.sendj(200,{"lineup":lineup(a["participant_id"],rid),"score":score(a["participant_id"],rid)})
            if m=="PUT":
                target=lineup_target_round()
                if not r or not target or rid!=target["id"] or r["status"] not in ("open","draft"):return self.sendj(400,{"error":"هذه الجولة غير متاحة لتعديل التشكيلة"})
                b=self.body();items=b.get("players",[]);ids=[i(x.get("player_id")) for x in items]
                if len(ids)!=8 or len(set(ids))!=8:return self.sendj(400,{"error":"يجب اختيار 8 لاعبين مختلفين"})
                ph=",".join(["?"]*8)
                if r["status"]=="draft":
                    ps=rows(f"SELECT id,group_no FROM players WHERE active=1 AND id IN ({ph})",tuple(ids))
                else:
                    snapshot_round(rid);ps=rows(f"SELECT player_id id,group_no FROM round_players WHERE round_id=? AND player_id IN ({ph})",(rid,*ids))
                counts={g:0 for g in range(1,5)}
                for x in ps:counts[x["group_no"]]+=1
                if len(ps)!=8 or any(counts[g]!=2 for g in counts):return self.sendj(400,{"error":"يجب اختيار لاعبين من كل مجموعة"})
                st=[x for x in items if x.get("role")=="starter"];be=[x for x in items if x.get("role")=="bench"]
                if len(st)!=6 or len(be)!=2:return self.sendj(400,{"error":"المطلوب 6 أساسيين و2 احتياط"})
                cap=i(b.get("captain_player_id"));vice=i(b.get("vice_player_id"));sid={i(x["player_id"]) for x in st}
                if cap==vice or cap not in sid or vice not in sid:return self.sendj(400,{"error":"الكبتن والنائب يجب أن يكونا أساسيين مختلفين"})
                chip=b.get("chip") or None
                if chip and chip in used_chips(a["participant_id"],rid):return self.sendj(400,{"error":"استخدمت هذه الطاقة سابقاً"})
                ex=row("SELECT id FROM lineups WHERE participant_id=? AND round_id=?",(a["participant_id"],rid))
                if ex:
                    lid=ex["id"];execq("UPDATE lineups SET captain_player_id=?,vice_player_id=?,chip=?,updated_at=? WHERE id=?",(cap,vice,chip,now(),lid));execq("DELETE FROM lineup_players WHERE lineup_id=?",(lid,))
                else:lid=insert_id("INSERT INTO lineups(participant_id,round_id,captain_player_id,vice_player_id,chip,submitted_at,updated_at) VALUES(?,?,?,?,?,?,?)",(a["participant_id"],rid,cap,vice,chip,now(),now()))
                for x in items:execq("INSERT INTO lineup_players(lineup_id,player_id,role,bench_order) VALUES(?,?,?,?)",(lid,i(x["player_id"]),x["role"],i(x.get("bench_order"))))
                if not PG:conn.commit()
                return self.sendj(200,{"ok":True})
        if p=="/api/account/profile" and a.get("participant_id"):
            if m=="GET":
                prof=row("SELECT u.id,u.name,u.username,u.profile_image,p.id player_id,p.group_no FROM participants u LEFT JOIN players p ON p.participant_id=u.id WHERE u.id=?",(a["participant_id"],))
                return self.sendj(200,prof or {})
            if m=="PUT":
                b=self.body()
                try:img=clean_profile_image(b.get("image"))
                except ValueError as e:return self.sendj(400,{"error":str(e)})
                execq("UPDATE participants SET profile_image=? WHERE id=?",(img,a["participant_id"]))
                if not PG:conn.commit()
                return self.sendj(200,{"ok":True,"profile_image":img})
        if m=="PUT" and p=="/api/account/code" and a.get("participant_id"):
            b=self.body();cur=row("SELECT code_hash FROM participants WHERE id=? AND active=1",(a["participant_id"],))
            current=str(b.get("current","")).strip();new=str(b.get("next","")).strip();confirm=str(b.get("confirm","")).strip()
            if not cur or h(current.upper(),"dawair-participant-v1")!=cur["code_hash"]:return self.sendj(400,{"error":"رمز الدخول الحالي غير صحيح"})
            if len(new)<4:return self.sendj(400,{"error":"رمز الدخول الجديد يجب أن يكون 4 أحرف على الأقل"})
            if new!=confirm:return self.sendj(400,{"error":"تأكيد رمز الدخول غير مطابق"})
            execq("UPDATE participants SET code_hash=?,code_hint=?,code_ciphertext=? WHERE id=?",(h(new.upper(),"dawair-participant-v1"),new[-3:].upper(),enc_code(new),a["participant_id"]))
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True})
        if not a.get("is_admin"):return self.sendj(403,{"error":"خاص بالمسؤول"})
        if m=="GET" and p=="/api/admin/dashboard":return self.sendj(200,{"players":val("SELECT COUNT(*) FROM players WHERE active=1"),"participants":val("SELECT COUNT(*) FROM participants WHERE active=1"),"rounds":val("SELECT COUNT(*) FROM rounds"),"lineups":val("SELECT COUNT(*) FROM lineups"),"leaderboard":leaderboard()[:10]})
        if len(parts)==4 and parts[:3]==["api","admin","lineups"] and m=="GET":
            rid=i(parts[3]);rnd=row("SELECT id,number,name,status FROM rounds WHERE id=?",(rid,))
            if not rnd:return self.sendj(404,{"error":"الجولة غير موجودة"})
            out=[]
            for u in rows("SELECT id,name,username,profile_image,active FROM participants ORDER BY name"):
                l=lineup(u["id"],rid)
                out.append({"participant":u,"lineup":l,"score":score(u["id"],rid) if l else 0})
            return self.sendj(200,{"round":rnd,"items":out})
        if m=="GET" and p=="/api/admin/participants":
            items=rows("SELECT u.id,u.name,u.username,u.code_hint,u.code_ciphertext,u.active,u.is_admin,p.id player_id,p.name player_name FROM participants u LEFT JOIN players p ON p.participant_id=u.id ORDER BY u.name")
            for x in items:x["code_full"]=dec_code(x.pop("code_ciphertext",None))
            return self.sendj(200,items)
        if m=="POST" and p=="/api/admin/participants":
            b=self.body();code=str(b.get("code","")).strip();un=norm_username(b.get("username",""));name=str(b.get("name","")).strip();pid=i(b.get("player_id"))
            if not valid_username(un):return self.sendj(400,{"error":"اليوزر يجب أن يكون 3-32 حرفاً، ويمكن أن يحتوي على مسافات داخلية"})
            if len(code)<4:return self.sendj(400,{"error":"رمز الدخول يجب أن يكون 4 أحرف على الأقل"})
            if row("SELECT id FROM participants WHERE username=?",(un,)):return self.sendj(400,{"error":"اليوزر مستخدم بالفعل"})
            if pid:
                pl=row("SELECT id,name,participant_id FROM players WHERE id=?",(pid,))
                if not pl:return self.sendj(400,{"error":"اللاعب غير موجود"})
                if pl.get("participant_id"):return self.sendj(400,{"error":"هذا اللاعب مربوط بحساب بالفعل"})
                name=pl["name"]
            if not name:return self.sendj(400,{"error":"اسم المشترك مطلوب"})
            try:
                uid=insert_id("INSERT INTO participants(name,username,code_hash,code_hint,code_ciphertext,active,created_at) VALUES(?,?,?,?,?,1,?)",(name,un,h(code.upper(),"dawair-participant-v1"),code[-3:].upper(),enc_code(code),now()))
                if pid:execq("UPDATE players SET participant_id=? WHERE id=?",(uid,pid))
                if not PG:conn.commit()
                return self.sendj(200,{"ok":True,"id":uid,"username":un})
            except:return self.sendj(400,{"error":"تعذر إنشاء الحساب؛ تحقق من اليوزر ورمز الدخول"})
        if len(parts)==4 and parts[:3]==["api","admin","participants"] and m=="PUT":
            b=self.body();uid=i(parts[3]);cur=row("SELECT * FROM participants WHERE id=?",(uid,))
            if not cur:return self.sendj(404,{"error":"الحساب غير موجود"})
            name=str(b.get("name",cur["name"])).strip();un=norm_username(b.get("username",cur.get("username") or ""));active=1 if b.get("active",bool(cur["active"])) else 0;is_admin=1 if b.get("is_admin",bool(cur.get("is_admin"))) else 0
            if not name or not valid_username(un):return self.sendj(400,{"error":"الاسم أو اليوزر غير صالح"})
            if row("SELECT id FROM participants WHERE username=? AND id<>?",(un,uid)):return self.sendj(400,{"error":"اليوزر مستخدم بالفعل"})
            if b.get("code"):
                code=str(b["code"]).strip()
                if len(code)<4:return self.sendj(400,{"error":"رمز الدخول يجب أن يكون 4 أحرف على الأقل"})
                execq("UPDATE participants SET name=?,username=?,active=?,is_admin=?,code_hash=?,code_hint=?,code_ciphertext=? WHERE id=?",(name,un,active,is_admin,h(code.upper(),"dawair-participant-v1"),code[-3:].upper(),enc_code(code),uid))
            else:execq("UPDATE participants SET name=?,username=?,active=?,is_admin=? WHERE id=?",(name,un,active,is_admin,uid))
            execq("UPDATE players SET name=? WHERE participant_id=?",(name,uid))
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True})
        if len(parts)==4 and parts[:3]==["api","admin","participants"] and m=="DELETE":
            uid=i(parts[3]);victim=row("SELECT id,name FROM participants WHERE id=?",(uid,))
            if not victim:return self.sendj(404,{"error":"الحساب غير موجود"})
            if a.get("participant_id")==uid:return self.sendj(400,{"error":"لا يمكنك حذف الحساب الذي تستخدمه حالياً"})
            lids=[x["id"] for x in rows("SELECT id FROM lineups WHERE participant_id=?",(uid,))]
            for lid in lids:execq("DELETE FROM lineup_players WHERE lineup_id=?",(lid,))
            execq("DELETE FROM lineups WHERE participant_id=?",(uid,))
            execq("UPDATE players SET participant_id=NULL WHERE participant_id=?",(uid,))
            execq("DELETE FROM participants WHERE id=?",(uid,))
            for token,sx in list(SESS.items()):
                if sx.get("participant_id")==uid:SESS.pop(token,None)
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True,"deleted":victim["name"]})
        if m=="GET" and p=="/api/admin/players":
            return self.sendj(200,rows("SELECT p.id,p.name,p.group_no,p.active,p.participant_id,u.username,u.name participant_name,u.profile_image,(SELECT rp.group_no FROM round_players rp JOIN rounds rr ON rr.id=rp.round_id WHERE rp.player_id=p.id AND rr.status=\'open\' ORDER BY rr.number DESC LIMIT 1) current_group_no FROM players p LEFT JOIN participants u ON u.id=p.participant_id ORDER BY p.group_no,p.name"))
        if m=="POST" and p=="/api/admin/players":
            b=self.body();g=i(b.get("group_no"));name=str(b.get("name","")).strip()
            if not name or g not in (1,2,3,4):return self.sendj(400,{"error":"بيانات اللاعب غير صحيحة"})
            return self.sendj(200,{"ok":True,"id":insert_id("INSERT INTO players(name,group_no,active,created_at) VALUES(?,?,1,?)",(name,g,now()))})
        if len(parts)==5 and parts[:3]==["api","admin","players"] and parts[4]=="link" and m=="POST":
            pid=i(parts[3]);pl=row("SELECT id,name FROM players WHERE id=?",(pid,));b=self.body()
            if not pl:return self.sendj(404,{"error":"اللاعب غير موجود"})
            un=norm_username(b.get("username",""))
            if not un:
                execq("UPDATE players SET participant_id=NULL WHERE id=?",(pid,))
                if not PG:conn.commit()
                return self.sendj(200,{"ok":True})
            u=row("SELECT id,username FROM participants WHERE username=?",(un,))
            if not u:return self.sendj(404,{"error":"لا يوجد حساب بهذا اليوزر"})
            if row("SELECT id FROM players WHERE participant_id=? AND id<>?",(u["id"],pid)):return self.sendj(400,{"error":"هذا الحساب مربوط بلاعب آخر"})
            execq("UPDATE players SET participant_id=? WHERE id=?",(u["id"],pid))
            execq("UPDATE participants SET name=? WHERE id=?",(pl["name"],u["id"]))
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True,"participant_id":u["id"],"username":u["username"]})
        if len(parts)==5 and parts[:3]==["api","admin","players"] and parts[4]=="account" and m=="POST":
            pid=i(parts[3]);pl=row("SELECT id,name,participant_id FROM players WHERE id=?",(pid,));b=self.body()
            if not pl:return self.sendj(404,{"error":"اللاعب غير موجود"})
            if pl.get("participant_id"):return self.sendj(400,{"error":"اللاعب مربوط بحساب بالفعل"})
            un=norm_username(b.get("username",""));code=str(b.get("code","")).strip()
            if not valid_username(un):return self.sendj(400,{"error":"اليوزر يجب أن يكون 3-32 حرفاً، ويمكن أن يحتوي على مسافات داخلية"})
            if len(code)<4:return self.sendj(400,{"error":"رمز الدخول يجب أن يكون 4 أحرف على الأقل"})
            if row("SELECT id FROM participants WHERE username=?",(un,)):return self.sendj(400,{"error":"اليوزر مستخدم بالفعل"})
            uid=insert_id("INSERT INTO participants(name,username,code_hash,code_hint,code_ciphertext,active,created_at) VALUES(?,?,?,?,?,1,?)",(pl["name"],un,h(code.upper(),"dawair-participant-v1"),code[-3:].upper(),enc_code(code),now()))
            execq("UPDATE players SET participant_id=? WHERE id=?",(uid,pid))
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True,"participant_id":uid,"username":un})
        if len(parts)==4 and parts[:3]==["api","admin","players"] and m=="PUT":
            b=self.body();pid=i(parts[3]);cur=row("SELECT * FROM players WHERE id=?",(pid,))
            if not cur:return self.sendj(404,{"error":"اللاعب غير موجود"})
            name=str(b.get("name",cur["name"])).strip();g=i(b.get("group_no",cur["group_no"]));active=1 if b.get("active",bool(cur["active"])) else 0
            link=i(b.get("participant_id",cur.get("participant_id") or 0))
            if not name or g not in (1,2,3,4):return self.sendj(400,{"error":"بيانات اللاعب غير صحيحة"})
            if link:
                u=row("SELECT id FROM participants WHERE id=?",(link,))
                if not u:return self.sendj(400,{"error":"الحساب غير موجود"})
                if row("SELECT id FROM players WHERE participant_id=? AND id<>?",(link,pid)):return self.sendj(400,{"error":"الحساب مربوط بلاعب آخر"})
            execq("UPDATE players SET name=?,group_no=?,active=?,participant_id=? WHERE id=?",(name,g,active,link or None,pid))
            if link:execq("UPDATE participants SET name=? WHERE id=?",(name,link))
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True})
        if m=="GET" and p=="/api/rounds":return self.sendj(200,rows("SELECT * FROM rounds ORDER BY number DESC"))
        if m=="POST" and p=="/api/admin/rounds":
            b=self.body();num=i(b.get("number"));return self.sendj(200,{"ok":True,"id":insert_id("INSERT INTO rounds(number,name,status,created_at) VALUES(?,?,?,?)",(num,b.get("name") or f"الجولة {num}",b.get("status") or "draft",now()))})
        if len(parts)==4 and parts[:3]==["api","admin","rounds"] and m=="PUT":
            b=self.body();rid=i(parts[3]);cur_r=row("SELECT * FROM rounds WHERE id=?",(rid,));st=b.get("status","draft")
            if not cur_r:return self.sendj(404,{"error":"الجولة غير موجودة"})
            if st=="open":
                execq("UPDATE rounds SET status='locked' WHERE status='open' AND id<>?",(rid,))
                snapshot_round(rid,True)
            execq("UPDATE rounds SET name=?,status=?,lock_at=? WHERE id=?",(b.get("name",cur_r["name"]),st,b.get("lock_at"),rid))
            if st in ("locked","scored"):ensure_next_round(cur_r["number"])
            conn.commit() if not PG else None
            return self.sendj(200,{"ok":True})
        if len(parts)==4 and parts[:3]==["api","admin","scores"]:
            rid=i(parts[3])
            if m=="GET":
                sr=row("SELECT * FROM rounds WHERE id=?",(rid,))
                if sr and sr["status"]!="draft":
                    snapshot_round(rid)
                    return self.sendj(200,rows("SELECT rp.player_id,rp.name,rp.group_no,COALESCE(e.goals,0) goals,COALESCE(e.wins,0) wins,COALESCE(e.hattricks,0) hattricks,COALESCE(e.attendance,0) attendance,COALESCE(e.best_player,0) best_player,COALESCE(e.yellow,0) yellow,COALESCE(e.red,0) red,COALESCE(e.no_shoes,0) no_shoes,COALESCE(e.own_goals,0) own_goals,COALESCE(e.raw_points,0) raw_points FROM round_players rp LEFT JOIN events e ON e.player_id=rp.player_id AND e.round_id=? WHERE rp.round_id=? ORDER BY rp.group_no,rp.name",(rid,rid)))
                return self.sendj(200,rows("SELECT p.id player_id,p.name,p.group_no,COALESCE(e.goals,0) goals,COALESCE(e.wins,0) wins,COALESCE(e.hattricks,0) hattricks,COALESCE(e.attendance,0) attendance,COALESCE(e.best_player,0) best_player,COALESCE(e.yellow,0) yellow,COALESCE(e.red,0) red,COALESCE(e.no_shoes,0) no_shoes,COALESCE(e.own_goals,0) own_goals,COALESCE(e.raw_points,0) raw_points FROM players p LEFT JOIN events e ON e.player_id=p.id AND e.round_id=? WHERE p.active=1 ORDER BY p.group_no,p.name",(rid,)))

            if m=="PUT":
                s=settings()
                for x in self.body().get("scores",[]):
                    e={k:i(x.get(k)) for k in ["goals","wins","hattricks","attendance","best_player","yellow","red","no_shoes","own_goals"]};pts=raw(e,s)
                    execq("INSERT INTO events(round_id,player_id,goals,wins,hattricks,attendance,best_player,yellow,red,no_shoes,own_goals,raw_points,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(round_id,player_id) DO UPDATE SET goals=excluded.goals,wins=excluded.wins,hattricks=excluded.hattricks,attendance=excluded.attendance,best_player=excluded.best_player,yellow=excluded.yellow,red=excluded.red,no_shoes=excluded.no_shoes,own_goals=excluded.own_goals,raw_points=excluded.raw_points,updated_at=excluded.updated_at",(rid,i(x["player_id"]),e["goals"],e["wins"],e["hattricks"],e["attendance"],e["best_player"],e["yellow"],e["red"],e["no_shoes"],e["own_goals"],pts,now()))
                conn.commit() if not PG else None;return self.sendj(200,{"ok":True})
        if m=="GET" and p=="/api/admin/settings":return self.sendj(200,settings())
        if m=="PUT" and p=="/api/admin/settings":
            for k,v in self.body().items():execq("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,str(v)))
            conn.commit() if not PG else None;return self.sendj(200,{"ok":True})
        if m=="PUT" and p=="/api/admin/password":
            b=self.body();np=str(b.get("next",""));current=str(b.get("current",""))
            if len(np)<8:return self.sendj(400,{"error":"8 أحرف على الأقل"})
            if a.get("participant_id"):
                cur=row("SELECT code_hash FROM participants WHERE id=?",(a["participant_id"],))
                if not cur or h(current.upper(),"dawair-participant-v1")!=cur["code_hash"]:return self.sendj(400,{"error":"كلمة المرور الحالية غير صحيحة"})
                execq("UPDATE participants SET code_hash=?,code_hint=?,code_ciphertext=? WHERE id=?",(h(np.upper(),"dawair-participant-v1"),np[-3:].upper(),enc_code(np),a["participant_id"]))
            else:
                ad=row("SELECT * FROM admins WHERE id=?",(a["id"],))
                if not ad or h(current,ad["salt"])!=ad["password_hash"]:return self.sendj(400,{"error":"كلمة المرور الحالية غير صحيحة"})
                salt=secrets.token_hex(16);execq("UPDATE admins SET password_hash=?,salt=? WHERE id=?",(h(np,salt),salt,a["id"]))
            if not PG:conn.commit()
            return self.sendj(200,{"ok":True})
        if m=="GET" and p=="/api/admin/backup":
            data={"exported_at":now(),"settings":rows("SELECT * FROM settings"),"participants":rows("SELECT id,name,username,code_hint,profile_image,active,is_admin,created_at FROM participants"),"players":rows("SELECT * FROM players"),"rounds":rows("SELECT * FROM rounds"),"round_players":rows("SELECT * FROM round_players"),"lineups":rows("SELECT * FROM lineups"),"lineup_players":rows("SELECT * FROM lineup_players"),"events":rows("SELECT * FROM events")}
            return self.sendj(200,data)
        return self.sendj(404,{"error":"المسار غير موجود"})

if __name__=="__main__":
    print("Fantasy Dawair cloud on",PORT,"DB","PostgreSQL" if PG else "SQLite")
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()
