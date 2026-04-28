"""
JUPITE — Application de rencontres
Backend Flask complet avec :
  - Géolocalisation (GPS + Haversine)
  - Système de pièces (200 à l'inscription, -40/message)
  - Paiement multi-devises (Carte, Orange Money, TMoney)
  - Réduction 50% pour les pays CFA
  - PWA installable (manifest + service worker)
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os, json, math, uuid
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'jupite-secret-2024-xK9mP')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jupite.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ══════════════════════════════════════════════
#  CONSTANTES MÉTIER
# ══════════════════════════════════════════════

PIECES_INSCRIPTION = 200
COUT_PAR_MESSAGE   = 40
REDUCTION_CFA      = 0.50   # 50 %

# Grille tarifaire (pièces ↔ USD)
OFFRES = [
    {'id': 0, 'pieces': 480,    'usd': 0.80,   'label': 'Starter',  'badge': ''},
    {'id': 1, 'pieces': 1000,   'usd': 1.50,   'label': 'Basic',    'badge': ''},
    {'id': 2, 'pieces': 1500,   'usd': 2.50,   'label': 'Standard', 'badge': '🔥'},
    {'id': 3, 'pieces': 3000,   'usd': 5.30,   'label': 'Premium',  'badge': '⭐'},
    {'id': 4, 'pieces': 10000,  'usd': 13.66,  'label': 'Gold',     'badge': '👑'},
    {'id': 5, 'pieces': 100000, 'usd': 140.30, 'label': 'Diamant',  'badge': '💎'},
]

# Pays utilisant le Franc CFA
PAYS_CFA = {
    'BJ','BF','CI','GW','ML','NE','SN','TG',   # UEMOA / XOF
    'CM','CF','TD','CG','GQ','GA',              # CEMAC / XAF
}
DEVISES_CFA = {'XOF', 'XAF', 'FCFA'}

# Taux de change vers USD  (1 USD = X unités locales)
TAUX = {
    'USD': 1.0,    'EUR': 0.92,   'GBP': 0.79,
    'XOF': 615.0,  'XAF': 615.0,  'NGN': 1580.0,
    'GHS': 15.8,   'KES': 131.0,  'ZAR': 18.6,
    'EGP': 30.9,   'MAD': 10.0,   'DZD': 134.5,
    'TND': 3.12,   'CAD': 1.37,   'CHF': 0.89,
    'JPY': 149.5,  'CNY': 7.24,   'INR': 83.1,
    'BRL': 4.97,   'MXN': 17.2,   'ARS': 870.0,
    'TRY': 31.5,   'RUB': 91.0,   'AED': 3.67,
    'SAR': 3.75,   'QAR': 3.64,   'VND': 24500.0,
    'IDR': 15700.0,'COP': 4000.0, 'CLP': 950.0,
}
SYMBOLES = {
    'USD':'$',  'EUR':'€',    'GBP':'£',    'XOF':'FCFA', 'XAF':'FCFA',
    'NGN':'₦',  'GHS':'GH₵',  'KES':'KSh',  'ZAR':'R',    'EGP':'E£',
    'MAD':'MAD','DZD':'DA',   'TND':'DT',   'CAD':'CA$',  'CHF':'CHF',
    'JPY':'¥',  'CNY':'¥',    'INR':'₹',    'BRL':'R$',   'MXN':'MX$',
    'ARS':'AR$','TRY':'₺',    'RUB':'₽',    'AED':'د.إ',  'SAR':'﷼',
    'QAR':'﷼',  'VND':'₫',    'IDR':'Rp',   'COP':'$',    'CLP':'$',
}

# ══════════════════════════════════════════════
#  MODÈLES
# ══════════════════════════════════════════════

class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    uuid       = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    username   = db.Column(db.String(50), unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    prenom     = db.Column(db.String(50))
    age        = db.Column(db.Integer)
    sexe       = db.Column(db.String(10))
    ville      = db.Column(db.String(100))
    pays       = db.Column(db.String(5), default='FR')
    devise     = db.Column(db.String(5), default='USD')
    lat        = db.Column(db.Float)
    lng        = db.Column(db.Float)
    bio        = db.Column(db.Text)
    interets   = db.Column(db.String(500))
    recherche  = db.Column(db.String(20))
    age_min    = db.Column(db.Integer, default=18)
    age_max    = db.Column(db.Integer, default=99)
    pieces     = db.Column(db.Integer, default=PIECES_INSCRIPTION)
    pieces_total_achete = db.Column(db.Integer, default=0)
    premium    = db.Column(db.Boolean, default=False)
    actif      = db.Column(db.Boolean, default=True)
    date_inscription   = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_connexion = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def est_cfa(self):
        return self.pays in PAYS_CFA or self.devise in DEVISES_CFA

    def to_dict(self, dist=None):
        d = {
            'id': self.id, 'username': self.username, 'prenom': self.prenom,
            'age': self.age, 'sexe': self.sexe, 'ville': self.ville,
            'pays': self.pays, 'devise': self.devise, 'bio': self.bio,
            'interets': json.loads(self.interets) if self.interets else [],
            'premium': self.premium, 'pieces': self.pieces,
            'lat': self.lat, 'lng': self.lng,
            'symbole': SYMBOLES.get(self.devise, self.devise),
        }
        if dist is not None:
            d['distance_km'] = dist
        return d


class Like(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date      = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('from_user', 'to_user'),)


class Match(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date     = db.Column(db.DateTime, default=datetime.utcnow)
    actif    = db.Column(db.Boolean, default=True)


class Message(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    match_id   = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    expediteur = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu    = db.Column(db.Text, nullable=False)
    lu         = db.Column(db.Boolean, default=False)
    pieces_cout = db.Column(db.Integer, default=COUT_PAR_MESSAGE)
    date       = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pieces        = db.Column(db.Integer, nullable=False)
    montant_usd   = db.Column(db.Float)
    montant_local = db.Column(db.Float)
    devise        = db.Column(db.String(5))
    symbole       = db.Column(db.String(6))
    moyen         = db.Column(db.String(20))  # carte / orange_money / tmoney
    reduction_cfa = db.Column(db.Boolean, default=False)
    reference     = db.Column(db.String(30))
    statut        = db.Column(db.String(20), default='simule')
    date          = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════

def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            if request.is_json:
                return jsonify({'success': False, 'code': 'AUTH_REQUIRED'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def haversine(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 1)

def prix_offre(idx, devise, est_cfa):
    offre = OFFRES[idx]
    usd = offre['usd'] * (1 - REDUCTION_CFA if est_cfa else 1)
    taux = TAUX.get(devise, 1.0)
    local = usd * taux
    # Arrondi propre selon la devise
    local = int(local) if taux >= 10 else round(local, 2)
    return {
        **offre,
        'usd_final': round(usd, 2),
        'prix_local': local,
        'devise': devise,
        'symbole': SYMBOLES.get(devise, devise),
        'reduction': est_cfa,
        'economie_pct': 50 if est_cfa else 0,
    }

def find_match(u1, u2):
    return Match.query.filter(
        ((Match.user1_id==u1)&(Match.user2_id==u2)) |
        ((Match.user1_id==u2)&(Match.user2_id==u1))
    ).first()


# ══════════════════════════════════════════════
#  PAGES HTML
# ══════════════════════════════════════════════

@app.route('/')
def index():
    return redirect(url_for('discover')) if current_user() else render_template('index.html')

@app.route('/inscription')
def inscription_page():
    return render_template('inscription.html')

@app.route('/connexion')
def login():
    return render_template('login.html')

@app.route('/decouvrir')
@login_required
def discover():
    return render_template('discover.html')

@app.route('/matches')
@login_required
def matches():
    return render_template('matches.html')

@app.route('/messages/<int:match_id>')
@login_required
def messages(match_id):
    m = Match.query.get_or_404(match_id)
    me = current_user()
    if me.id not in [m.user1_id, m.user2_id]:
        return redirect(url_for('matches'))
    return render_template('messages.html', match_id=match_id)

@app.route('/profil')
@login_required
def profil():
    return render_template('profil.html')

@app.route('/recharger')
@login_required
def recharger():
    return render_template('recharger.html')

@app.route('/deconnexion')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ══════════════════════════════════════════════
#  API AUTH
# ══════════════════════════════════════════════

@app.route('/api/inscription', methods=['POST'])
def api_inscription():
    d = request.get_json()
    if User.query.filter_by(email=d['email']).first():
        return jsonify({'success': False, 'message': 'Email déjà utilisé'})
    if User.query.filter_by(username=d['username']).first():
        return jsonify({'success': False, 'message': "Pseudo déjà pris"})

    pays   = (d.get('pays') or 'FR').upper()
    devise = (d.get('devise') or 'USD').upper()

    u = User(
        username  = d['username'], email=d['email'],
        password  = generate_password_hash(d['password']),
        prenom    = d.get('prenom',''), age=int(d.get('age',18)),
        sexe      = d.get('sexe',''), ville=d.get('ville',''),
        bio       = d.get('bio',''),
        interets  = json.dumps(d.get('interets',[])),
        recherche = d.get('recherche','les_deux'),
        pays=pays, devise=devise,
        lat=d.get('lat'), lng=d.get('lng'),
        pieces=PIECES_INSCRIPTION,
    )
    db.session.add(u)
    db.session.commit()
    session['user_id'] = u.id
    return jsonify({'success': True, 'redirect': '/decouvrir',
                    'pieces_bienvenue': PIECES_INSCRIPTION})

@app.route('/api/connexion', methods=['POST'])
def api_connexion():
    d = request.get_json()
    u = User.query.filter_by(email=d['email']).first()
    if u and check_password_hash(u.password, d['password']):
        session['user_id'] = u.id
        u.derniere_connexion = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'redirect': '/decouvrir'})
    return jsonify({'success': False, 'message': 'Identifiants incorrects'})


# ════════════════════════════════════════════
#  API GÉOLOCALISATION
# ════════════════════════════════════════════

@app.route('/api/position', methods=['POST'])
@login_required
def api_position():
    me = current_user()
    d  = request.get_json()
    if d.get('lat') and d.get('lng'):
        me.lat = float(d['lat'])
        me.lng = float(d['lng'])
        if d.get('ville'):  me.ville = d['ville']
        if d.get('pays'):   me.pays  = d['pays'].upper()
        if d.get('devise'): me.devise = d['devise'].upper()
        db.session.commit()
        return jsonify({'success': True, 'lat': me.lat, 'lng': me.lng})
    return jsonify({'success': False, 'message': 'Coordonnées manquantes'})


# ══════════════════════════════════════════════
#  API PROFILS / SWIPE
# ══════════════════════════════════════════════

@app.route('/api/profils')
@login_required
def api_profils():
    me    = current_user()
    rayon = float(request.args.get('rayon', 9999))
    vus   = db.session.query(Like.to_user).filter_by(from_user=me.id).subquery()

    q = User.query.filter(User.id!=me.id, User.actif==True, ~User.id.in_(vus))
    if me.recherche and me.recherche != 'les_deux':
        q = q.filter(User.sexe == me.recherche)
    if me.age_min: q = q.filter(User.age >= me.age_min)
    if me.age_max: q = q.filter(User.age <= me.age_max)

    result = []
    for p in q.limit(60).all():
        d = haversine(me.lat, me.lng, p.lat, p.lng)
        if d is not None and d > rayon: continue
        result.append(p.to_dict(dist=d))

    result.sort(key=lambda x: x.get('distance_km') or 9999)
    return jsonify(result[:20])

@app.route('/api/like', methods=['POST'])
@login_required
def api_like():
    me = current_user()
    d  = request.get_json()
    tid, action = d.get('user_id'), d.get('action','like')
    if action == 'pass':
        return jsonify({'success': True, 'match': False})
    if not Like.query.filter_by(from_user=me.id, to_user=tid).first():
        db.session.add(Like(from_user=me.id, to_user=tid))
        db.session.commit()
    if Like.query.filter_by(from_user=tid, to_user=me.id).first() and not find_match(me.id, tid):
        db.session.add(Match(user1_id=me.id, user2_id=tid))
        db.session.commit()
        return jsonify({'success': True, 'match': True, 'profil': User.query.get(tid).to_dict()})
    return jsonify({'success': True, 'match': False})


# ══════════════════════════════════════════════
#  API MATCHES
# ══════════════════════════════════════════════

@app.route('/api/matches')
@login_required
def api_matches():
    me = current_user()
    ms = Match.query.filter(
        ((Match.user1_id==me.id)|(Match.user2_id==me.id)) & Match.actif
    ).all()
    out = []
    for m in ms:
        oid = m.user2_id if m.user1_id==me.id else m.user1_id
        o   = User.query.get(oid)
        if not o: continue
        lm  = Message.query.filter_by(match_id=m.id).order_by(Message.date.desc()).first()
        r   = o.to_dict()
        r.update({'match_id': m.id,
                  'dernier_message': lm.contenu[:50] if lm else None,
                  'date_match': m.date.strftime('%d/%m/%Y')})
        out.append(r)
    return jsonify(out)


# ══════════════════════════════════════════════
#  API MESSAGES
# ══════════════════════════════════════════════

@app.route('/api/messages/<int:mid>')
@login_required
def api_get_messages(mid):
    me   = current_user()
    msgs = Message.query.filter_by(match_id=mid).order_by(Message.date.asc()).all()
    Message.query.filter_by(match_id=mid, lu=False)\
        .filter(Message.expediteur!=me.id).update({'lu': True})
    db.session.commit()
    return jsonify([{'id':m.id,'contenu':m.contenu,'date':m.date.strftime('%H:%M'),
                     'moi':m.expediteur==me.id} for m in msgs])

@app.route('/api/messages/envoyer', methods=['POST'])
@login_required
def api_send():
    me = current_user()
    d  = request.get_json()

    # ── CONTRÔLE PIÈCES ──
    if me.pieces < COUT_PAR_MESSAGE:
        return jsonify({
            'success': False, 'code': 'PIECES_INSUFFISANTES',
            'message': f'Il vous faut {COUT_PAR_MESSAGE} pièces pour envoyer un message.',
            'pieces': me.pieces, 'cout': COUT_PAR_MESSAGE
        }), 402

    me.pieces -= COUT_PAR_MESSAGE
    msg = Message(match_id=d['match_id'], expediteur=me.id,
                  contenu=d['contenu'], pieces_cout=COUT_PAR_MESSAGE)
    db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True, 'pieces': me.pieces, 'cout': COUT_PAR_MESSAGE})


# ══════════════════════════════════════════════
#  API PIÈCES & PAIEMENT
# ══════════════════════════════════════════════

@app.route('/api/pieces/solde')
@login_required
def api_solde():
    me = current_user()
    return jsonify({
        'pieces': me.pieces,
        'cout_message': COUT_PAR_MESSAGE,
        'messages_possibles': me.pieces // COUT_PAR_MESSAGE,
        'est_cfa': me.est_cfa,
        'devise': me.devise,
        'symbole': SYMBOLES.get(me.devise, me.devise),
    })

@app.route('/api/pieces/offres')
@login_required
def api_offres():
    me     = current_user()
    devise = request.args.get('devise', me.devise).upper()
    est_cfa = me.est_cfa or devise in DEVISES_CFA
    return jsonify({
        'offres': [prix_offre(i, devise, est_cfa) for i in range(len(OFFRES))],
        'est_cfa': est_cfa, 'devise': devise,
        'symbole': SYMBOLES.get(devise, devise),
        'cout_message': COUT_PAR_MESSAGE,
    })

@app.route('/api/pieces/convertir')
def api_convertir():
    """Convertit un montant USD en devise locale (avec réduction CFA si applicable)."""
    usd    = float(request.args.get('usd', 0))
    devise = request.args.get('devise', 'USD').upper()
    est_cfa = devise in DEVISES_CFA
    if est_cfa:
        usd *= (1 - REDUCTION_CFA)
    taux = TAUX.get(devise, 1.0)
    local = usd * taux
    local = int(local) if taux >= 10 else round(local, 2)
    return jsonify({
        'usd': round(usd, 2), 'local': local,
        'devise': devise, 'symbole': SYMBOLES.get(devise, devise),
        'taux': taux, 'reduction_cfa': est_cfa,
    })

@app.route('/api/pieces/acheter', methods=['POST'])
@login_required
def api_acheter():
    """
    Crédite les pièces après paiement simulé.
    En production → intégrer :
      - Carte bancaire : Stripe / CinetPay
      - Orange Money   : Orange Money API (CinetPay / Bizao)
      - TMoney         : TMoney API Togo
    """
    me  = current_user()
    d   = request.get_json()
    idx = int(d.get('offre_idx', 0))
    moyen  = d.get('moyen', 'carte')
    devise = (d.get('devise') or me.devise).upper()

    if idx < 0 or idx >= len(OFFRES):
        return jsonify({'success': False, 'message': 'Offre invalide'})

    est_cfa = me.est_cfa or devise in DEVISES_CFA
    p       = prix_offre(idx, devise, est_cfa)
    ref     = 'JUP-' + uuid.uuid4().hex[:10].upper()

    tx = Transaction(
        user_id=me.id, pieces=p['pieces'],
        montant_usd=p['usd_final'], montant_local=p['prix_local'],
        devise=devise, symbole=p['symbole'],
        moyen=moyen, reduction_cfa=est_cfa,
        reference=ref, statut='simule',
    )
    db.session.add(tx)
    me.pieces += p['pieces']
    me.pieces_total_achete += p['pieces']
    db.session.commit()

    return jsonify({
        'success': True, 'reference': ref,
        'pieces_ajoutees': p['pieces'],
        'nouveau_solde': me.pieces,
        'montant': f"{p['prix_local']} {p['symbole']}",
        'reduction_cfa': est_cfa,
        'message': f"✅ {p['pieces']:,} pièces créditées !",
    })

@app.route('/api/pieces/historique')
@login_required
def api_historique():
    me  = current_user()
    txs = Transaction.query.filter_by(user_id=me.id).order_by(Transaction.date.desc()).limit(30).all()
    return jsonify([{
        'id': t.id, 'pieces': t.pieces,
        'montant': f"{t.montant_local} {t.symbole}",
        'moyen': t.moyen, 'reference': t.reference,
        'reduction_cfa': t.reduction_cfa,
        'date': t.date.strftime('%d/%m/%Y %H:%M'),
        'statut': t.statut,
    } for t in txs])

@app.route('/api/devises')
def api_devises():
    return jsonify([
        {'code': k, 'symbole': SYMBOLES.get(k, k), 'taux_usd': v}
        for k, v in TAUX.items()
    ])


# ══════════════════════════════════════════════
#  API PROFIL
# ══════════════════════════════════════════════

@app.route('/api/profil/moi')
@login_required
def api_moi():
    me = current_user()
    d  = me.to_dict()
    d.update({'email': me.email, 'recherche': me.recherche,
              'age_min': me.age_min, 'age_max': me.age_max,
              'est_cfa': me.est_cfa})
    return jsonify(d)

@app.route('/api/profil/modifier', methods=['POST'])
@login_required
def api_modifier():
    me = current_user()
    d  = request.get_json()
    for f in ['prenom','age','ville','bio','recherche','age_min','age_max','pays','devise']:
        if f in d: setattr(me, f, d[f])
    if 'interets' in d: me.interets = json.dumps(d['interets'])
    if d.get('lat'): me.lat = float(d['lat'])
    if d.get('lng'): me.lng = float(d['lng'])
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/stats')
@login_required
def api_stats():
    me = current_user()
    return jsonify({
        'likes_recus':  Like.query.filter_by(to_user=me.id).count(),
        'matches':      Match.query.filter((Match.user1_id==me.id)|(Match.user2_id==me.id)).count(),
        'messages':     Message.query.filter_by(expediteur=me.id).count(),
        'pieces':       me.pieces,
        'messages_possibles': me.pieces // COUT_PAR_MESSAGE,
    })


# ══════════════════════════════════════════════
#  PWA — manifest & service worker
# ══════════════════════════════════════════════

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "JUPITE",
        "short_name": "JUPITE",
        "description": "L'application de rencontres JUPITE",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0E0B14",
        "theme_color": "#E8364A",
        "orientation": "portrait",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ],
        "categories": ["social", "lifestyle"],
        "screenshots": [],
    }), 200, {'Content-Type': 'application/manifest+json'}

@app.route('/sw.js')
def service_worker():
    sw = """
const CACHE = 'jupite-v1';
const ASSETS = ['/', '/decouvrir', '/matches', '/profil', '/recharger'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  if(e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
"""
    return sw, 200, {'Content-Type': 'application/javascript'}


# ══════════════════════════════════════════════
#  INIT DB
# ══════════════════════════════════════════════

def seed():
    if User.query.count() > 0: return
    demos = [
        {'u':'sophie_m',  'e':'sophie@demo.com',  'p':'Sophie',  'a':26,'s':'femme','v':'Abidjan',  'pays':'CI','dev':'XOF','lat':5.35,  'lng':-4.00},
        {'u':'thomas_r',  'e':'thomas@demo.com',  'p':'Thomas',  'a':29,'s':'homme','v':'Paris',    'pays':'FR','dev':'EUR','lat':48.85, 'lng':2.35},
        {'u':'camille_d', 'e':'camille@demo.com', 'p':'Camille', 'a':24,'s':'femme','v':'Lomé',     'pays':'TG','dev':'XOF','lat':6.13,  'lng':1.22},
        {'u':'lucas_b',   'e':'lucas@demo.com',   'p':'Lucas',   'a':31,'s':'homme','v':'Dakar',    'pays':'SN','dev':'XOF','lat':14.69, 'lng':-17.44},
        {'u':'emma_v',    'e':'emma@demo.com',     'p':'Emma',    'a':27,'s':'femme','v':'Lyon',     'pays':'FR','dev':'EUR','lat':45.74, 'lng':4.83},
        {'u':'kofi_a',    'e':'kofi@demo.com',    'p':'Kofi',    'a':30,'s':'homme','v':'Accra',    'pays':'GH','dev':'GHS','lat':5.56,  'lng':-0.19},
        {'u':'ines_b',    'e':'ines@demo.com',    'p':'Inès',    'a':25,'s':'femme','v':'Casablanca','pays':'MA','dev':'MAD','lat':33.58, 'lng':-7.59},
    ]
    for d in demos:
        u = User(
            username=d['u'], email=d['e'],
            password=generate_password_hash('demo1234'),
            prenom=d['p'], age=d['a'], sexe=d['s'], ville=d['v'],
            pays=d['pays'], devise=d['dev'], lat=d['lat'], lng=d['lng'],
            interets=json.dumps(['Voyage','Musique','Sport']),
            recherche='les_deux', pieces=PIECES_INSCRIPTION,
        )
        db.session.add(u)
    db.session.commit()
    print("✅ Données de démo créées")

if __name__ == '__main__':
    os.makedirs('static/uploads', exist_ok=True)
    os.makedirs('static/icons', exist_ok=True)
    with app.app_context():
        db.create_all()
        seed()
    print("🚀 JUPITE → http://localhost:5000")
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)




import re
from PIL import Image
import pytesseract

# ================================
# 🔒 1. LISTE NOIRE (mots interdits)
# ================================
# Tous les mots liés aux réseaux sociaux ou partage de contact
BLACKLIST_WORDS = [
    "whatsapp", "instagram", "snapchat", "telegram", "facebook",
    "fb", "insta", "snap", "contact", "num", "numero"
]


# ================================
# 🧠 2. NORMALISATION DU TEXTE
# ================================
def normalize_text(text):
    """
    Nettoie le texte pour éviter les contournements :
    - supprime espaces, points, symboles
    - met en minuscule
    Exemple :
    "i.n.s.t.a" → "insta"
    "0 6 12 34" → "061234"
    """
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())


# ================================
# 🔢 3. DETECTION NUMERO
# ================================
def contains_phone_number(text):
    """
    Détecte un numéro même avec espaces ou tirets
    """
    return re.search(r'(\+?\d[\d\s\-]{7,})', text)


# ================================
# 🌐 4. DETECTION LIENS
# ================================
def contains_link(text):
    """
    Détecte les URLs
    """
    return re.search(r'(https?://|www\.)', text)


# ================================
# 🚫 5. DETECTION MOTS INTERDITS
# ================================
def contains_blacklist_words(text):
    """
    Vérifie les mots interdits (version normale)
    """
    text = text.lower()
    return any(word in text for word in BLACKLIST_WORDS)


# ================================
# 🧠 6. DETECTION AVANCEE (ANTI-CONTOURNEMENT)
# ================================
def advanced_detection(text):
    """
    Analyse la version nettoyée pour détecter :
    - mots cachés (i.n.s.t.a)
    - numéros cachés (0 6 12 34)
    """
    normalized = normalize_text(text)

    # 🚫 mots interdits cachés
    if any(word in normalized for word in BLACKLIST_WORDS):
        return True

    # 🔢 numéro caché (suite de chiffres)
    if re.search(r'\d{8,}', normalized):
        return True

    return False


# ================================
# 🖼️ 7. EXTRACTION TEXTE IMAGE (OCR)
# ================================
def extract_text_from_image(image_path):
    """
    Lit le texte dans une image (screenshot, photo)
    """
    try:
        img = Image.open(image_path)
        return pytesseract.image_to_string(img)
    except:
        return ""


# ================================
# 🔍 8. VALIDATION IMAGE
# ================================
def is_image_allowed(image_path):
    """
    Vérifie si une image est autorisée
    """

    # 📄 extraire le texte de l'image
    text = extract_text_from_image(image_path)

    # 🔢 numéro dans image
    if contains_phone_number(text):
        return False

    # 🚫 mots interdits
    if contains_blacklist_words(text):
        return False

    # 🧠 contournement
    if advanced_detection(text):
        return False

    return True


# ================================
# ✅ 9. VALIDATION MESSAGE TEXTE (PRINCIPALE)
# ================================
def is_message_allowed(text):
    """
    Fonction principale :
    retourne True → message OK
    retourne False → message BLOQUÉ
    """

    # 🔢 numéro direct
    if contains_phone_number(text):
        return False

    # 🌐 lien
    if contains_link(text):
        return False

    # 🚫 mots interdits visibles
    if contains_blacklist_words(text):
        return False

    # 🧠 contournement
    if advanced_detection(text):
        return False

    return True


# ================================
# 🚀 10. UTILISATION (ENVOI MESSAGE)
# ================================
if __name__ == "__main__":

    message = "Ajoute moi sur insta : john_doe"

    # ⛔ si interdit → on bloque
    if not is_message_allowed(message):
        print("⛔ Message bloqué → il ne sera PAS envoyé")

    else:
        print("✅ Message autorisé → envoi en cours")
        # 👉 ici tu envoies réellement le message (API, base de données, etc)


        import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Chemin correct vers la base dans instance/
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'instance', 'jupite.db')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

