import streamlit as st
import sqlite3
import json
import os
from dotenv import load_dotenv
from google import genai
from datetime import datetime, date
from pathlib import Path

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "krushisetu.db"

# Load local environment variables from .env (never commit the real .env file).
load_dotenv(APP_DIR / ".env")

st.set_page_config(page_title="कृषीसेतू | अर्ज व्यवस्थापन", page_icon="🌾", layout="wide")

STAGES = ["अर्ज प्राप्त", "कागदपत्र पडताळणी", "क्षेत्रीय तपासणी", "अंतिम निर्णय"]
STATUSES = ["प्रलंबित", "मंजूर", "नामंजूर", "दुरुस्तीसाठी परत"]

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_no TEXT UNIQUE, farmer TEXT, village TEXT, scheme TEXT,
            mobile TEXT, amount REAL, submitted TEXT, stage TEXT,
            status TEXT, notes TEXT, documents TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_no TEXT, action TEXT, details TEXT, actor TEXT, created_at TEXT
        )""")
        # Demo requirement: use one common contact number for every application.
        con.execute("UPDATE applications SET mobile = ?", ("1234567890",))
        count = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        if count == 0:
            samples = [
                ("AGR-1024","सचिन शिंदे","आळंदी","ठिबक सिंचन अनुदान","1234567890",45000,"2026-10-29",STAGES[1],"प्रलंबित","7/12 व बँक पासबुक उपलब्ध. नावातील तफावत तपासणे आवश्यक.","7/12 उतारा, बँक पासबुक, आधार कार्ड"),
                ("AGR-1025","सविता पवार","चऱ्होली","शेततळे अनुदान","1234567890",75000,"2026-10-30",STAGES[2],"प्रलंबित","स्थळ तपासणी अहवाल बाकी.","7/12 उतारा, फोटो, बँक पासबुक"),
                ("AGR-1026","गणेश जाधव","मोशी","ठिबक सिंचन अनुदान","1234567890",38000,"2026-10-25",STAGES[3],"प्रलंबित","सर्व कागदपत्रे प्राप्त. अंतिम निर्णय बाकी.","7/12 उतारा, बँक पासबुक, आधार कार्ड"),
                ("AGR-1027","मीनाक्षी कदम","चिखली","कृषी यांत्रिकीकरण अनुदान","1234567890",52000,"2026-10-27",STAGES[0],"प्रलंबित","अर्जाची प्राथमिक तपासणी बाकी.","अर्ज, कोटेशन"),
                ("AGR-1028","विठ्ठल गायकवाड","डुडुळगाव","शेततळे अनुदान","1234567890",60000,"2026-10-20",STAGES[3],"मंजूर","पात्रता व तपासणी पूर्ण.","7/12 उतारा, फोटो, बँक पासबुक"),
            ]
            for row in samples:
                con.execute("INSERT INTO applications(app_no,farmer,village,scheme,mobile,amount,submitted,stage,status,notes,documents) VALUES(?,?,?,?,?,?,?,?,?,?,?)", row)
            for row in samples:
                con.execute("INSERT INTO history(app_no,action,details,actor,created_at) VALUES(?,?,?,?,?)",
                            (row[0], "अर्ज नोंदवला", "डेमो अर्ज प्रणालीमध्ये नोंदवला.", "प्रणाली", datetime.now().isoformat(timespec="minutes")))

def log(app_no, action, details, actor="अधिकारी"):
    with db() as con:
        con.execute("INSERT INTO history(app_no,action,details,actor,created_at) VALUES(?,?,?,?,?)",
                    (app_no, action, details, actor, datetime.now().isoformat(timespec="minutes")))

def get_apps():
    with db() as con:
        return con.execute("SELECT * FROM applications ORDER BY submitted DESC").fetchall()

def ai_review(app):
    """Gemini कडून मराठी प्राथमिक अर्ज विश्लेषण."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    # Streamlit Community Cloud stores secrets in st.secrets, not in a local .env file.
    if not api_key:
        try:
            api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
        except Exception:
            api_key = ""
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY सापडली नाही. Local वापरासाठी .env आणि Cloud साठी App Settings > Secrets मध्ये key सेट करा.")

    prompt = f"""
तू महाराष्ट्रातील सरकारी कृषी कार्यालयातील अधिकाऱ्याला मदत करणारा मराठी AI सहाय्यक आहेस.
खालील अर्जाची माहिती वाचून केवळ प्राथमिक विश्लेषण दे. कोणताही अंतिम निर्णय घेऊ नकोस.
योजनेची पात्रता किंवा कागदपत्रांची सत्यता निश्चित असल्याचा दावा करू नकोस.
फक्त दिलेल्या माहितीवर आधारित मुद्दे मांड. माहिती अपुरी असल्यास ते स्पष्ट सांग.

अर्ज क्रमांक: {app['app_no']}
शेतकऱ्याचे नाव: {app['farmer']}
गाव: {app['village']}
योजना: {app['scheme']}
मागितलेली रक्कम: ₹{app['amount']:,.0f}
अर्ज दिनांक: {app['submitted']}
सध्याचा टप्पा: {app['stage']}
स्थिती: {app['status']}
नोंदी: {app['notes']}
नोंदवलेली कागदपत्रे: {app['documents']}

उत्तर मराठीत या शीर्षकांखाली दे:
१. अर्जाचा संक्षिप्त सारांश
२. उपलब्ध माहितीतील निरीक्षणे
३. अधिकाऱ्याने तपासावयाच्या संभाव्य त्रुटी / अपूर्ण माहिती
४. पुढील कार्यवाहीसाठी सूचना
५. मर्यादा व मानवी पडताळणी
"""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
    )
    if not response.text:
        raise RuntimeError("Gemini कडून मजकूर प्रतिसाद मिळाला नाही.")
    return response.text

init_db()

# ---------- Visual design ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Hind Siliguri', 'Inter', sans-serif; }
[data-testid="stAppViewContainer"] { background: #f6f8f6; }
[data-testid="stHeader"] { background: rgba(246,248,246,.92); }
.block-container { max-width: 1440px; padding-top: 1.2rem; padding-bottom: 3rem; }
[data-testid="stSidebar"] { background: #edf4ef; border-right: 1px solid #dce8df; }
[data-testid="stSidebar"] > div { padding-top: 1.2rem; }
h1, h2, h3 { color: #173f2d; letter-spacing: -.2px; }
p, label, .stMarkdown { color: #26352d; }
div[data-testid="stMetric"] {
  background: #ffffff; border: 1px solid #e1e9e3; border-radius: 16px;
  padding: 16px 18px; box-shadow: 0 2px 10px rgba(28,62,42,.04);
}
div[data-testid="stMetric"] label { color: #64756a; font-size: .92rem; }
div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #173f2d; font-weight: 700; }
div.stButton > button, div.stDownloadButton > button, button[kind] {
  border-radius: 10px; min-height: 2.65rem; font-weight: 600;
  border: 1px solid #d5e2d8; transition: all .15s ease;
}
div.stButton > button[kind="primary"], button[kind="primary"] {
  background: #176b43; border-color: #176b43; color: white;
}
div.stButton > button:hover { border-color: #176b43; color: #176b43; }
div.stButton > button[kind="primary"]:hover { background: #125536; color: white; }
div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea,
div[data-testid="stSelectbox"] div[data-baseweb="select"] {
  border-radius: 10px;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: #e1e9e3; border-radius: 15px; background: #fff;
}
.ks-hero {
  background: linear-gradient(115deg,#164b32 0%,#23734a 100%);
  padding: 24px 28px; border-radius: 18px; color: white; margin-bottom: 22px;
  box-shadow: 0 8px 22px rgba(22,75,50,.12);
}
.ks-hero h1 { color: white !important; margin: 0; font-size: 2rem; }
.ks-hero p { color: #e0f0e5 !important; margin: 6px 0 0 0; }
.ks-muted { color:#718078; font-size:.88rem; }
.ks-section { margin-top: 1.2rem; margin-bottom: .45rem; }
.ks-chip { display:inline-block; border-radius:999px; padding:4px 10px; font-size:.82rem; font-weight:600; }
.ks-green { background:#e7f5eb; color:#176b43; }
.ks-yellow { background:#fff4d9; color:#916000; }
.ks-red { background:#fde9e7; color:#a3342b; }
.ks-gray { background:#edf0ee; color:#59665e; }
.ks-appno { color:#176b43; font-size:.82rem; font-weight:700; letter-spacing:.3px; }
.ks-card-title { font-size:1.08rem; font-weight:700; color:#203b2b; }
.ks-step { padding:10px 12px; border:1px solid #e1e9e3; border-radius:10px; text-align:center; background:white; }
.ks-step-active { background:#e7f5eb; border-color:#8fc5a0; color:#176b43; font-weight:700; }
footer {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

def navigate_to(page, app_no=None):
    """Sidebar navigation callback; callbacks run before widgets are instantiated."""
    st.session_state["nav"] = page
    if app_no:
        st.session_state["selected_app"] = app_no
        st.session_state["detail_view"] = True

def status_chip(status):
    cls = {
        "प्रलंबित": "ks-yellow",
        "मंजूर": "ks-green",
        "नामंजूर": "ks-red",
        "दुरुस्तीसाठी परत": "ks-gray",
    }.get(status, "ks-gray")
    return f'<span class="ks-chip {cls}">{status}</span>'

with st.sidebar:
    st.markdown("## 🌾 कृषीसेतू")
    st.caption("शेतकरी अनुदान अर्ज व्यवस्थापन")
    st.markdown("---")
    page = st.radio(
        "मुख्य मेनू",
        ["आढावा", "अर्ज व्यवस्थापन", "नवीन अर्ज", "अहवाल व माहिती"],
        key="nav",
        label_visibility="visible",
    )
    st.markdown("---")
    st.markdown("**👤 Demo Officer**")
    st.caption("कार्यालयीन वापरासाठी नमुना प्रणाली")
    st.caption("मराठी इंटरफेस · AI सहाय्य")

apps = get_apps()
pending = [a for a in apps if a["status"] == "प्रलंबित"]
approved = [a for a in apps if a["status"] == "मंजूर"]
rejected = [a for a in apps if a["status"] == "नामंजूर"]
returned = [a for a in apps if a["status"] == "दुरुस्तीसाठी परत"]

st.markdown(
    '<div class="ks-hero"><h1>कृषीसेतू</h1>'
    '<p>शेतकरी अनुदान अर्जांची पारदर्शक, सोपी आणि टप्प्याटप्प्याने कार्यवाही</p></div>',
    unsafe_allow_html=True,
)

if page == "आढावा":
    st.subheader("आजचा कार्यालयीन आढावा")
    st.caption("प्रलंबित अर्ज ओळखा, प्राधान्य ठरवा आणि पुढील कार्यवाही करा.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("एकूण अर्ज", len(apps), help="प्रणालीमध्ये नोंदवलेले सर्व अर्ज")
    c2.metric("प्रलंबित", len(pending), help="अजून अंतिम निर्णय न झालेल्या अर्जांची संख्या")
    c3.metric("मंजूर", len(approved))
    c4.metric("नामंजूर / परत", len(rejected) + len(returned))

    st.markdown('<div class="ks-section"></div>', unsafe_allow_html=True)
    left, right = st.columns([1.5, 1])
    with left:
        st.markdown("### 🚩 तातडीने लक्ष देण्याचे अर्ज")
        urgent = sorted(pending, key=lambda a: (a["stage"] != "अंतिम निर्णय", a["submitted"]))
        if urgent:
            for a in urgent[:5]:
                with st.container(border=True):
                    top = st.columns([2.2, 1, 1])
                    top[0].markdown(f'<div class="ks-appno">{a["app_no"]}</div><div class="ks-card-title">{a["farmer"]}</div><div class="ks-muted">{a["village"]} · {a["scheme"]}</div>', unsafe_allow_html=True)
                    top[1].markdown(f'<div class="ks-muted">सध्याचा टप्पा</div><b>{a["stage"]}</b>', unsafe_allow_html=True)
                    top[2].markdown(f'<div class="ks-muted">अनुदान रक्कम</div><b>₹{a["amount"]:,.0f}</b>', unsafe_allow_html=True)
                    st.button(
                        "अर्ज तपासा  →",
                        key=f"dash_open_{a['app_no']}",
                        on_click=navigate_to,
                        args=("अर्ज व्यवस्थापन", a["app_no"]),
                    )
        else:
            st.success("सध्या कोणतेही प्रलंबित अर्ज नाहीत.")
    with right:
        st.markdown("### 📌 अर्जांची स्थिती")
        if apps:
            st.progress(len(approved) / len(apps))
            st.write(f"**{len(approved)} / {len(apps)}** अर्ज मंजूर")
            st.caption("ही माहिती प्रणालीतील सध्याच्या नोंदींवर आधारित आहे.")
        st.markdown("### ⚡ जलद कृती")
        st.button(
            "＋ नवीन अर्ज नोंदवा",
            use_container_width=True,
            on_click=navigate_to,
            args=("नवीन अर्ज",),
        )
        st.button(
            "सर्व अर्ज पहा",
            use_container_width=True,
            on_click=navigate_to,
            args=("अर्ज व्यवस्थापन",),
        )
        st.info("प्राधान्य सूचना ही केवळ सहाय्यक क्रमवारी आहे. प्रत्यक्ष प्राधान्य अधिकाऱ्याने ठरवावे.")

elif page == "अर्ज व्यवस्थापन":
    selected = st.session_state.get("selected_app")
    chosen = next((a for a in apps if a["app_no"] == selected), None)
    detail_view = st.session_state.get("detail_view", False)

    if chosen and detail_view:
        if st.button("← सर्व अर्जांकडे परत", key="back_to_applications"):
            st.session_state["detail_view"] = False
            st.rerun()
        st.caption("सध्या निवडलेल्या अर्जाचीच माहिती दाखवली आहे.")
    else:
        st.subheader("अर्ज व्यवस्थापन")
        st.caption("अर्ज शोधा, तपशील तपासा आणि पुढील कार्यवाही नोंदवा.")
        f1, f2 = st.columns([2, 1])
        q = f1.text_input("🔎 अर्ज क्रमांक, शेतकऱ्याचे नाव किंवा गाव शोधा", placeholder="उदा. AGR-1024 / सचिन / आळंदी")
        status_filter = f2.selectbox("स्थिती", ["सर्व"] + STATUSES)
        filtered = [
            a for a in apps
            if (status_filter == "सर्व" or a["status"] == status_filter)
            and (not q or q.lower() in " ".join([a["app_no"], a["farmer"], a["village"], a["scheme"]]).lower())
        ]
        st.caption(f"एकूण {len(filtered)} अर्ज दिसत आहेत")
        if not filtered:
            st.warning("या शोधासाठी अर्ज सापडला नाही. शोध शब्द किंवा फिल्टर बदला.")
        for a in filtered:
            with st.container(border=True):
                x, y, z = st.columns([2.2, 1.5, 1])
                x.markdown(f'<div class="ks-appno">{a["app_no"]}</div><div class="ks-card-title">{a["farmer"]}</div><div class="ks-muted">{a["village"]} · {a["scheme"]}</div>', unsafe_allow_html=True)
                y.markdown(f'{status_chip(a["status"])}<div class="ks-muted" style="margin-top:8px">{a["stage"]}</div>', unsafe_allow_html=True)
                z.markdown(f'<div class="ks-muted">मागितलेली रक्कम</div><div class="ks-card-title">₹{a["amount"]:,.0f}</div><div class="ks-muted">{a["submitted"]}</div>', unsafe_allow_html=True)
                if st.button("तपशील उघडा  →", key=f"detail_{a['app_no']}"):
                    st.session_state["selected_app"] = a["app_no"]
                    st.session_state["detail_view"] = True
                    st.rerun()


    if chosen and st.session_state.get("detail_view", False):
        if chosen:
            st.markdown("---")
            st.markdown(f"## {chosen['farmer']}  <span class='ks-appno'>{chosen['app_no']}</span>", unsafe_allow_html=True)
            st.markdown(status_chip(chosen["status"]), unsafe_allow_html=True)
            t1, t2, t3, t4 = st.tabs(["📄 अर्ज तपशील", "🤖 AI सहाय्य", "📝 कार्यवाही", "🕘 इतिहास"])
            with t1:
                a1, a2 = st.columns(2)
                with a1:
                    st.markdown("**अर्जदाराची माहिती**")
                    st.write(f"**गाव:** {chosen['village']}")
                    st.write(f"**मोबाईल:** {chosen['mobile'] or 'नोंद नाही'}")
                    st.write(f"**योजना:** {chosen['scheme']}")
                with a2:
                    st.markdown("**अर्जाची माहिती**")
                    st.write(f"**अर्ज दिनांक:** {chosen['submitted']}")
                    st.write(f"**मागितलेली रक्कम:** ₹{chosen['amount']:,.0f}")
                    st.write(f"**कागदपत्रे:** {chosen['documents'] or 'नोंद नाही'}")
                st.markdown("**अधिकाऱ्याच्या नोंदी**")
                st.info(chosen["notes"] or "अद्याप कोणतीही नोंद नाही.")
                st.markdown("**प्रक्रियेतील टप्पे**")
                cols = st.columns(4)
                current_idx = STAGES.index(chosen["stage"]) if chosen["stage"] in STAGES else 0
                for i, stage in enumerate(STAGES):
                    cols[i].markdown(
                        f'<div class="ks-step {"ks-step-active" if i <= current_idx else ""}">'
                        f'<small>टप्पा {i+1}</small><br><b>{stage}</b></div>',
                        unsafe_allow_html=True
                    )
            with t2:
                st.markdown("### Gemini AI प्राथमिक विश्लेषण")
                st.caption("AI अर्जातील उपलब्ध माहितीचा सारांश आणि तपासणी मुद्दे देतो. तो पात्रता निश्चित करत नाही किंवा निर्णय घेत नाही.")
                if st.button("✨ Gemini कडून विश्लेषण मिळवा", type="primary", key=f"ai_{chosen['app_no']}"):
                    try:
                        with st.spinner("Gemini अर्जाचे विश्लेषण करत आहे..."):
                            result = ai_review(chosen)
                        st.session_state["ai_result"] = result
                        st.session_state["ai_result_app"] = chosen["app_no"]
                        log(chosen["app_no"], "Gemini AI विश्लेषण", "Gemini कडून प्राथमिक विश्लेषण तयार केले.")
                    except Exception as e:
                        st.error(f"AI विश्लेषण करता आले नाही: {e}")
                if st.session_state.get("ai_result") and st.session_state.get("ai_result_app") == chosen["app_no"]:
                    st.markdown(st.session_state["ai_result"])
                st.warning("AI सूचना फक्त सहाय्यक आहेत. मूळ कागदपत्रे व योजनेचे अधिकृत नियम तपासून अंतिम निर्णय अधिकाऱ्याने घ्यावा.")
            with t3:
                st.markdown("### अधिकाऱ्याची कार्यवाही")
                if chosen["status"] == "प्रलंबित":
                    new_stage = st.selectbox("अर्जाचा पुढील टप्पा", STAGES, index=STAGES.index(chosen["stage"]), key=f"stage_{chosen['app_no']}")
                    note = st.text_area("कार्यवाहीची नोंद / निर्णयाचे कारण *", key=f"note_{chosen['app_no']}", placeholder="उदा. 7/12 उताऱ्यावरील तपशील तपासला...")
                    a, b = st.columns(2)
                    with a:
                        if st.button("टप्पा अद्ययावत करा", key=f"advance_{chosen['app_no']}", use_container_width=True):
                            with db() as con:
                                con.execute("UPDATE applications SET stage=?, notes=? WHERE app_no=?", (new_stage, note, chosen["app_no"]))
                            log(chosen["app_no"], "टप्पा अद्ययावत", f"नवीन टप्पा: {new_stage}. नोंद: {note}")
                            st.success("टप्पा यशस्वीरीत्या अद्ययावत झाला.")
                            st.rerun()
                    with b:
                        st.caption("अंतिम निर्णय घेताना कारण नोंदवणे आवश्यक आहे.")
                    d1, d2, d3 = st.columns(3)
                    if d1.button("✓ मंजूर करा", type="primary", key=f"approve_{chosen['app_no']}", use_container_width=True):
                        if not note.strip():
                            st.error("मंजुरीची नोंद लिहा.")
                        else:
                            with db() as con:
                                con.execute("UPDATE applications SET status=?, stage=?, notes=? WHERE app_no=?", ("मंजूर", STAGES[3], note, chosen["app_no"]))
                            log(chosen["app_no"], "अर्ज मंजूर", note)
                            st.success("अर्ज मंजूर म्हणून नोंदवला.")
                            st.rerun()
                    if d2.button("✕ नामंजूर करा", key=f"reject_{chosen['app_no']}", use_container_width=True):
                        if not note.strip():
                            st.error("नकाराचे कारण लिहा.")
                        else:
                            with db() as con:
                                con.execute("UPDATE applications SET status=?, notes=? WHERE app_no=?", ("नामंजूर", note, chosen["app_no"]))
                            log(chosen["app_no"], "अर्ज नामंजूर", note)
                            st.warning("अर्ज नामंजूर म्हणून नोंदवला.")
                            st.rerun()
                    if d3.button("↩ दुरुस्तीसाठी परत", key=f"return_{chosen['app_no']}", use_container_width=True):
                        if not note.strip():
                            st.error("परत पाठवण्याचे कारण लिहा.")
                        else:
                            with db() as con:
                                con.execute("UPDATE applications SET status=?, notes=? WHERE app_no=?", ("दुरुस्तीसाठी परत", note, chosen["app_no"]))
                            log(chosen["app_no"], "अर्ज परत पाठवला", note)
                            st.info("अर्ज दुरुस्तीसाठी परत पाठवला.")
                            st.rerun()
                else:
                    st.info("या अर्जावर अंतिम स्थिती नोंदवलेली आहे. इतिहास टॅबमध्ये आधीच्या कार्यवाही पाहता येतील.")
            with t4:
                with db() as con:
                    hist = con.execute("SELECT * FROM history WHERE app_no=? ORDER BY id DESC", (chosen["app_no"],)).fetchall()
                if hist:
                    for h in hist:
                        with st.container(border=True):
                            st.markdown(f"**{h['action']}** · {h['created_at']}")
                            st.write(h["details"])
                            st.caption(f"नोंद करणारे: {h['actor']}")
                else:
                    st.info("या अर्जासाठी इतिहास उपलब्ध नाही.")

elif page == "नवीन अर्ज":
    st.subheader("नवीन शेतकरी अर्ज")
    st.caption("तारांकित (*) माहिती भरणे आवश्यक आहे.")
    with st.container(border=True):
        with st.form("new_application", clear_on_submit=True, enter_to_submit=False):
            a, b = st.columns(2)
            farmer = a.text_input("शेतकऱ्याचे पूर्ण नाव *", placeholder="उदा. गणेश जाधव")
            village = b.text_input("गावाचे नाव *", placeholder="उदा. मोशी")
            scheme = a.selectbox("योजना निवडा", ["ठिबक सिंचन अनुदान", "शेततळे अनुदान", "कृषी यांत्रिकीकरण अनुदान", "इतर"])
            mobile = b.text_input("मोबाईल क्रमांक", value="1234567890", max_chars=10, disabled=True)
            amount = a.number_input("मागितलेली अनुदान रक्कम (₹)", min_value=0, step=1000)
            submitted = b.date_input("अर्ज दिनांक", value=date.today())
            docs = st.text_input("प्राप्त कागदपत्रे", "7/12 उतारा, बँक पासबुक")
            notes = st.text_area("प्राथमिक नोंद", placeholder="अर्जाबाबत प्राथमिक निरीक्षण...")
            submit = st.form_submit_button("अर्ज नोंदवा", type="primary", use_container_width=True)
    if submit:
        if not farmer.strip() or not village.strip():
            st.error("शेतकऱ्याचे नाव आणि गाव आवश्यक आहे.")
        elif mobile and (not mobile.isdigit() or len(mobile) != 10):
            st.error("मोबाईल क्रमांक 10 अंकी असावा.")
        else:
            app_no = "AGR-" + datetime.now().strftime("%y%m%d%H%M%S")
            try:
                with db() as con:
                    con.execute("INSERT INTO applications(app_no,farmer,village,scheme,mobile,amount,submitted,stage,status,notes,documents) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (app_no, farmer, village, scheme, mobile, amount, submitted.isoformat(), STAGES[0], "प्रलंबित", notes, docs))
                log(app_no, "नवीन अर्ज प्राप्त", "नवीन अर्ज प्रणालीमध्ये नोंदवला.")
                st.success(f"अर्ज यशस्वीरीत्या नोंदवला. अर्ज क्रमांक: {app_no}")
            except sqlite3.IntegrityError:
                st.error("अर्ज क्रमांक आधीपासून अस्तित्वात आहे. पुन्हा प्रयत्न करा.")

elif page == "अहवाल व माहिती":
    st.subheader("अहवाल आणि प्रणालीविषयी माहिती")
    st.caption("नोंदवलेल्या अर्जांची स्थिती आणि प्रक्रिया पाहा.")
    rows = [{"अर्ज क्रमांक": a["app_no"], "शेतकरी": a["farmer"], "गाव": a["village"], "योजना": a["scheme"], "टप्पा": a["stage"], "स्थिती": a["status"]} for a in apps]
    st.dataframe(rows, width="stretch", hide_index=True)
    csv_data = "अर्ज क्रमांक,शेतकरी,गाव,योजना,टप्पा,स्थिती\n" + "\n".join(
        ",".join('"' + str(v).replace('"', '""') + '"' for v in row.values()) for row in rows
    )
    st.download_button("⬇ अर्ज अहवाल CSV डाउनलोड करा", data=csv_data.encode("utf-8-sig"), file_name="krushisetu_report.csv", mime="text/csv")
    st.markdown("### प्रणालीविषयी")
    st.write("कृषीसेतू ही शेतकरी अनुदान अर्जांची नोंद, टप्प्यांनुसार कार्यवाही, Gemini AI प्राथमिक सहाय्य आणि निर्णय इतिहास दाखवण्यासाठी तयार केलेली नमुना प्रणाली आहे.")
    st.warning("ही शैक्षणिक डेमो प्रणाली आहे. प्रत्यक्ष सरकारी निर्णय, लाभार्थी माहिती किंवा अधिकृत योजनेची पात्रता निश्चित करण्यासाठी वापरू नये.")

st.divider()
st.caption("कृषीसेतू · डेमो प्रणाली | AI सूचना निर्णयाचा पर्याय नाहीत. अंतिम निर्णय अधिकृत कर्मचाऱ्याचाच.")
