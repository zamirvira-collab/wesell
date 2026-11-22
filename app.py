import os, sqlite3, secrets, re
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

ROOT=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('WESELL_DB',os.path.join(ROOT,'wesell.db'))
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY',secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE')=='1',MAX_CONTENT_LENGTH=1024*1024)
STATUSES=['new','dealer_review','appointment_proposed','confirmed','visited','sold_pending','sold_verified','no_sale','cancelled']
GAS=['Shell','Chevron','76','ARCO','ExxonMobil','Other']

def db():
    if 'db' not in g:
        g.db=sqlite3.connect(DB,timeout=15)
        g.db.row_factory=sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db
@app.teardown_appcontext
def close_db(_):
    conn=g.pop('db',None)
    if conn:conn.close()

def init_db():
    conn=sqlite3.connect(DB)
    conn.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,name TEXT NOT NULL,phone TEXT DEFAULT '',role TEXT NOT NULL CHECK(role IN ('buyer','dealer','admin')),dealer_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS dealers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,city TEXT NOT NULL,approved INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS vehicles(id INTEGER PRIMARY KEY,dealer_id INTEGER NOT NULL REFERENCES dealers(id),year INTEGER NOT NULL,make TEXT NOT NULL,model TEXT NOT NULL,trim TEXT DEFAULT '',price INTEGER NOT NULL,mileage INTEGER NOT NULL,vin TEXT DEFAULT '',image_url TEXT DEFAULT '',description TEXT DEFAULT '',active INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY,vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),buyer_id INTEGER NOT NULL REFERENCES users(id),dealer_id INTEGER NOT NULL REFERENCES dealers(id),status TEXT NOT NULL DEFAULT 'new',buyer_note TEXT DEFAULT '',dealer_note TEXT DEFAULT '',appointment_time TEXT DEFAULT '',gas_station TEXT DEFAULT 'Shell',purchase_verified_at TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS lead_events(id INTEGER PRIMARY KEY,lead_id INTEGER NOT NULL REFERENCES leads(id),actor_role TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS rewards(id INTEGER PRIMARY KEY,lead_id INTEGER UNIQUE NOT NULL REFERENCES leads(id),station TEXT NOT NULL,amount INTEGER DEFAULT 25,status TEXT DEFAULT 'pending' CHECK(status IN ('pending','issued')),issued_at TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_vehicle_dealer ON vehicles(dealer_id);
    CREATE INDEX IF NOT EXISTS idx_leads_dealer ON leads(dealer_id);
    CREATE INDEX IF NOT EXISTS idx_leads_buyer ON leads(buyer_id);
    ''')
    if conn.execute('SELECT COUNT(*) FROM dealers').fetchone()[0]==0:
        conn.execute("INSERT INTO dealers(name,city) VALUES('Pacific Coast Auto Group','San Diego, CA'),('Mission Valley Motors','San Diego, CA')")
        vehicles=[(1,2019,'Nissan','Pathfinder','SV',15995,111349,'5N1DR2MM3KC637462','https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?w=900&q=85','Family-friendly SUV'),(1,2020,'Mercedes-Benz','C-Class','C 300',21995,117155,'','https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?w=900&q=85','Luxury sedan'),(2,2018,'Ford','Explorer','Sport',17995,113624,'','https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?w=900&q=85','Spacious SUV'),(2,2017,'Jeep','Compass','High Altitude',11995,93168,'','https://images.unsplash.com/photo-1503376780353-7e6692767b70?w=900&q=85','Versatile crossover'),(1,2019,'Jeep','Renegade','Altitude',14995,81381,'','https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?w=900&q=85','Compact SUV'),(2,2018,'Volkswagen','Tiguan','2.0T',13995,115385,'','https://images.unsplash.com/photo-1541899481282-d53bffe3c35d?w=900&q=85','Comfortable daily driver')]
        conn.executemany('INSERT INTO vehicles(dealer_id,year,make,model,trim,price,mileage,vin,image_url,description) VALUES(?,?,?,?,?,?,?,?,?,?)',vehicles)
    if os.environ.get('WESELL_SEED_DEMO')=='1':
        for email,pw,name,role,dealer_id in [('admin@wesell.local','AdminDemo123!','WE-SELL Admin','admin',None),('dealer@wesell.local','DealerDemo123!','Dealer Manager','dealer',1),('buyer@wesell.local','BuyerDemo123!','Demo Buyer','buyer',None)]:
            conn.execute('INSERT OR IGNORE INTO users(email,password_hash,name,role,dealer_id) VALUES(?,?,?,?,?)',(email,generate_password_hash(pw),name,role,dealer_id))
    conn.commit();conn.close()

@app.before_request
def load_user():
    g.user=None
    if session.get('uid'):
        g.user=db().execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone()
        if not g.user:session.clear()
    if request.method=='POST':
        if not session.get('csrf') or not secrets.compare_digest(request.form.get('csrf',''),session['csrf']):abort(400,'Invalid form token. Reload and try again.')

@app.context_processor
def inject():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
    return {'me':g.get('user'),'csrf':session['csrf'],'statuses':STATUSES}

def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            if not g.user:return redirect(url_for('login',next=request.path))
            if role and g.user['role']!=role:abort(403)
            return fn(*args,**kwargs)
        return wrapper
    return deco

def event(lead_id,role,message):db().execute('INSERT INTO lead_events(lead_id,actor_role,message) VALUES(?,?,?)',(lead_id,role,message))

def lead_for_role(lead_id):
    lead=db().execute('''SELECT l.*,v.year,v.make,v.model,v.trim,v.vin,v.price,v.image_url,d.name dealer_name,u.name buyer_name,u.email buyer_email,u.phone buyer_phone FROM leads l JOIN vehicles v ON l.vehicle_id=v.id JOIN dealers d ON l.dealer_id=d.id JOIN users u ON l.buyer_id=u.id WHERE l.id=?''',(lead_id,)).fetchone()
    if not lead:abort(404)
    role=g.user['role']
    if role=='buyer' and lead['buyer_id']!=g.user['id']:abort(403)
    if role=='dealer' and lead['dealer_id']!=g.user['dealer_id']:abort(403)
    return lead

@app.get('/')
def home():
    q=request.args.get('q','').strip()[:100];make=request.args.get('make','').strip()[:50]
    sql='''SELECT v.*,d.name dealer_name,d.city FROM vehicles v JOIN dealers d ON v.dealer_id=d.id WHERE v.active=1 AND d.approved=1''';args=[]
    if q:sql+=' AND (v.make LIKE ? OR v.model LIKE ? OR v.trim LIKE ? OR CAST(v.year AS TEXT) LIKE ?)';args+=['%'+q+'%']*4
    if make:sql+=' AND v.make=?';args.append(make)
    sql+=' ORDER BY v.created_at DESC,v.id DESC'
    vehicles=db().execute(sql,args).fetchall()
    makes=db().execute('SELECT DISTINCT make FROM vehicles WHERE active=1 ORDER BY make').fetchall()
    return render_template('home.html',vehicles=vehicles,makes=makes,q=q,selected_make=make)

@app.get('/vehicle/<int:vid>')
def vehicle(vid):
    v=db().execute('SELECT v.*,d.name dealer_name,d.city FROM vehicles v JOIN dealers d ON v.dealer_id=d.id WHERE v.id=? AND v.active=1',(vid,)).fetchone()
    if not v:abort(404)
    return render_template('vehicle.html',v=v)

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip()[:100];email=request.form.get('email','').strip().lower()[:254];password=request.form.get('password','');phone=request.form.get('phone','').strip()[:30]
        if not name or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(password)<10:flash('Enter your name, valid email, and a password of at least 10 characters.','error')
        else:
            try:
                cur=db().execute('INSERT INTO users(email,password_hash,name,phone,role) VALUES(?,?,?,?,?)',(email,generate_password_hash(password),name,phone,'buyer'));db().commit();session.clear();session['uid']=cur.lastrowid;flash('Account created. Welcome to WE-SELL!','success');return redirect(url_for('home'))
            except sqlite3.IntegrityError:flash('This email is already registered.','error')
    return render_template('auth.html',mode='register')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=db().execute('SELECT * FROM users WHERE email=?',(request.form.get('email','').strip().lower(),)).fetchone()
        if u and check_password_hash(u['password_hash'],request.form.get('password','')):
            session.clear();session['uid']=u['id'];flash('Welcome back!','success')
            return redirect(url_for('dashboard'))
        flash('Incorrect email or password.','error')
    return render_template('auth.html',mode='login')

@app.post('/logout')
def logout():session.clear();return redirect(url_for('home'))

@app.get('/dashboard')
@login_required()
def dashboard():
    if g.user['role']=='buyer':return redirect(url_for('buyer_dashboard'))
    if g.user['role']=='dealer':return redirect(url_for('dealer_dashboard'))
    return redirect(url_for('admin_dashboard'))

@app.post('/inquire/<int:vid>')
@login_required('buyer')
def inquire(vid):
    v=db().execute('SELECT * FROM vehicles WHERE id=? AND active=1',(vid,)).fetchone()
    if not v:abort(404)
    station=request.form.get('gas_station','Shell')
    if station not in GAS:abort(400)
    note=request.form.get('note','').strip()[:1000]
    cur=db().execute('INSERT INTO leads(vehicle_id,buyer_id,dealer_id,buyer_note,gas_station,status) VALUES(?,?,?,?,?,?)',(vid,g.user['id'],v['dealer_id'],note,station,'new'))
    event(cur.lastrowid,'system','Buyer inquiry received by WE-SELL. Awaiting dealership review.')
    db().commit();flash('Your inquiry was received. WE-SELL will coordinate with the dealership.','success');return redirect(url_for('lead_detail',lead_id=cur.lastrowid))

@app.get('/buyer')
@login_required('buyer')
def buyer_dashboard():
    leads=db().execute('''SELECT l.*,v.year,v.make,v.model,v.image_url FROM leads l JOIN vehicles v ON v.id=l.vehicle_id WHERE l.buyer_id=? ORDER BY l.id DESC''',(g.user['id'],)).fetchall()
    return render_template('buyer.html',leads=leads)

@app.get('/dealer')
@login_required('dealer')
def dealer_dashboard():
    leads=db().execute('''SELECT l.*,v.year,v.make,v.model,v.vin,u.name buyer_name FROM leads l JOIN vehicles v ON v.id=l.vehicle_id JOIN users u ON u.id=l.buyer_id WHERE l.dealer_id=? ORDER BY l.id DESC''',(g.user['dealer_id'],)).fetchall()
    vehicles=db().execute('SELECT * FROM vehicles WHERE dealer_id=? ORDER BY id DESC',(g.user['dealer_id'],)).fetchall()
    return render_template('dealer.html',leads=leads,vehicles=vehicles)

@app.route('/dealer/vehicles/new',methods=['GET','POST'])
@login_required('dealer')
def add_vehicle():
    if request.method=='POST':
        try:
            year=int(request.form['year']);price=int(request.form['price']);mileage=int(request.form['mileage'])
            assert 1980<=year<=datetime.now().year+2 and 0<=price<=10000000 and 0<=mileage<=2000000
            make=request.form['make'].strip()[:50];model=request.form['model'].strip()[:50]
            assert make and model
        except (ValueError,KeyError,AssertionError):flash('Check required vehicle fields and numeric values.','error');return render_template('add_vehicle.html')
        db().execute('INSERT INTO vehicles(dealer_id,year,make,model,trim,price,mileage,vin,image_url,description) VALUES(?,?,?,?,?,?,?,?,?,?)',(g.user['dealer_id'],year,make,model,request.form.get('trim','').strip()[:80],price,mileage,request.form.get('vin','').strip().upper()[:17],request.form.get('image_url','').strip()[:500],request.form.get('description','').strip()[:2000]));db().commit();flash('Vehicle listed.','success');return redirect(url_for('dealer_dashboard'))
    return render_template('add_vehicle.html')

@app.post('/dealer/vehicles/<int:vid>/toggle')
@login_required('dealer')
def toggle_vehicle(vid):
    v=db().execute('SELECT * FROM vehicles WHERE id=? AND dealer_id=?',(vid,g.user['dealer_id'])).fetchone()
    if not v:abort(404)
    db().execute('UPDATE vehicles SET active=? WHERE id=?',(0 if v['active'] else 1,vid));db().commit();return redirect(url_for('dealer_dashboard'))

@app.get('/leads/<int:lead_id>')
@login_required()
def lead_detail(lead_id):
    lead=lead_for_role(lead_id)
    events=db().execute('SELECT * FROM lead_events WHERE lead_id=? ORDER BY id DESC',(lead_id,)).fetchall()
    reward=db().execute('SELECT * FROM rewards WHERE lead_id=?',(lead_id,)).fetchone()
    return render_template('lead.html',lead=lead,events=events,reward=reward,gas=GAS)

@app.post('/leads/<int:lead_id>/dealer-response')
@login_required('dealer')
def dealer_response(lead_id):
    lead=lead_for_role(lead_id)
    if lead['status'] not in ('new','dealer_review','appointment_proposed'):abort(400,'This lead is not awaiting dealer response.')
    action=request.form.get('action');note=request.form.get('note','').strip()[:1000]
    if action=='propose':
        appt=request.form.get('appointment_time','').strip()
        try:
            parsed=datetime.fromisoformat(appt);assert parsed>datetime.now()
        except (ValueError,AssertionError):flash('Provide a future appointment time.','error');return redirect(url_for('lead_detail',lead_id=lead_id))
        db().execute('UPDATE leads SET status=?,appointment_time=?,dealer_note=? WHERE id=?',('appointment_proposed',appt,note,lead_id));event(lead_id,'dealer','Dealer confirmed availability and proposed appointment: '+appt+'. '+note)
    elif action=='unavailable':
        db().execute('UPDATE leads SET status=?,dealer_note=? WHERE id=?',('cancelled',note,lead_id));event(lead_id,'dealer','Vehicle unavailable. '+note)
    else:abort(400)
    db().commit();flash('Response saved for the buyer in WE-SELL.','success');return redirect(url_for('lead_detail',lead_id=lead_id))

@app.post('/leads/<int:lead_id>/buyer-response')
@login_required('buyer')
def buyer_response(lead_id):
    lead=lead_for_role(lead_id)
    if lead['status']!='appointment_proposed':abort(400)
    action=request.form.get('action');status='confirmed' if action=='accept' else 'cancelled' if action=='decline' else None
    if not status:abort(400)
    db().execute('UPDATE leads SET status=? WHERE id=?',(status,lead_id));event(lead_id,'buyer','Buyer '+('accepted appointment.' if status=='confirmed' else 'declined appointment.'));db().commit();flash('Appointment response saved.','success');return redirect(url_for('lead_detail',lead_id=lead_id))

@app.post('/leads/<int:lead_id>/sale')
@login_required('dealer')
def sale(lead_id):
    lead=lead_for_role(lead_id)
    if lead['status'] not in ('confirmed','visited'):abort(400,'An appointment must be confirmed first.')
    db().execute('UPDATE leads SET status=? WHERE id=?',('sold_pending',lead_id));event(lead_id,'dealer','Dealership reported completed purchase. Awaiting WE-SELL verification.');db().commit();flash('Sale reported for WE-SELL verification.','success');return redirect(url_for('lead_detail',lead_id=lead_id))

@app.get('/admin')
@login_required('admin')
def admin_dashboard():
    leads=db().execute('''SELECT l.*,v.year,v.make,v.model,d.name dealer_name,u.name buyer_name FROM leads l JOIN vehicles v ON v.id=l.vehicle_id JOIN dealers d ON d.id=l.dealer_id JOIN users u ON u.id=l.buyer_id ORDER BY l.id DESC''').fetchall()
    stats={k:db().execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for k,t in [('vehicles','vehicles'),('dealers','dealers'),('buyers','users WHERE role="buyer"'),('leads','leads')]}
    return render_template('admin.html',leads=leads,stats=stats)

@app.post('/admin/leads/<int:lead_id>/verify')
@login_required('admin')
def verify_sale(lead_id):
    lead=lead_for_role(lead_id)
    if lead['status']!='sold_pending':abort(400,'Sale must first be reported by dealer.')
    db().execute('UPDATE leads SET status=?,purchase_verified_at=CURRENT_TIMESTAMP WHERE id=?',('sold_verified',lead_id))
    db().execute('INSERT OR IGNORE INTO rewards(lead_id,station,amount,status) VALUES(?,?,25,?)',(lead_id,lead['gas_station'],'pending'))
    event(lead_id,'admin','WE-SELL verified the purchase. $25 gas reward eligible; issuance pending.');db().commit();flash('Purchase verified; gift-card reward queued.','success');return redirect(url_for('lead_detail',lead_id=lead_id))

@app.post('/admin/leads/<int:lead_id>/issue-reward')
@login_required('admin')
def issue_reward(lead_id):
    lead=lead_for_role(lead_id)
    if lead['status']!='sold_verified':abort(400)
    reward=db().execute('SELECT * FROM rewards WHERE lead_id=?',(lead_id,)).fetchone()
    if not reward or reward['status']=='issued':abort(400)
    # Record issuance only after an operator has actually sent a gift card outside the system.
    db().execute("UPDATE rewards SET status='issued',issued_at=CURRENT_TIMESTAMP WHERE lead_id=?",(lead_id,));event(lead_id,'admin','Gift-card delivery marked complete by administrator.');db().commit();flash('Reward marked issued.','success');return redirect(url_for('lead_detail',lead_id=lead_id))

@app.get('/how-it-works')
def how_it_works():return render_template('how.html')
@app.get('/dealers')
def dealers_page():return render_template('dealers_info.html')


init_db()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG') == '1'
    )
