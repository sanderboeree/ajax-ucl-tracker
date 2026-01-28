# ucl_tracker_fd.py
# Single-file server + client for UEFA Champions League tracker using Football-Data.org API.
# Default port: 8088
# NOTE: Do NOT hard-code secrets. Supply FD_TOKEN via environment.

import os
import sys
import argparse
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# === Configuration ===
FD_API_BASE = 'https://api.football-data.org/v4'
FD_API_TOKEN = os.getenv('FD_TOKEN')  # <- no default; set in Render env
DEFAULT_PORT = int(os.getenv('PORT', '8088'))
COMPETITION_CODE = 'CL'  # UEFA Champions League

# --- Favicon (SVG) ---
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <style>
      .bg { fill: #0a0a0a; }
      .ring { fill: none; stroke: #D2122E; stroke-width: 6; }
      .A { fill: #ffffff; font-family: Teko, Arial, sans-serif; font-weight: 700; font-size: 34px; }
    </style>
  </defs>
  <rect class="bg" x="0" y="0" width="64" height="64" rx="12" ry="12"/>
  <circle class="ring" cx="32" cy="32" r="22"/>
  <text class="A" x="50%" y="54%" text-anchor="middle" dominant-baseline="middle">A</text>
</svg>
"""

# We'll lazily create an ICO from the SVG on first request.
# (Basic conversion by rasterizing with Pillow if available; else we serve the SVG as a fallback.)
FAVICON_ICO_BYTES = None
def _lazy_make_ico():
    global FAVICON_ICO_BYTES
    if FAVICON_ICO_BYTES is not None:
        return FAVICON_ICO_BYTES
    try:
        # Attempt to rasterize with Pillow (usually available on Render)
        from PIL import Image
        import io, base64
        # Convert SVG -> PNG via cairosvg if present; otherwise simple text-to-image fallback.
        # To avoid optional deps, we’ll render a minimal PNG using Pillow drawing.
        img = Image.new("RGBA", (64, 64), (10, 10, 10, 255))  # dark bg
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(img)
        # ring
        d.ellipse((10, 10, 54, 54), outline=(210, 18, 46, 255), width=6)
        # "A"
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        w, h = d.textsize("A", font=font)
        d.text((32 - w/2, 32 - h/2 + 4), "A", fill=(255, 255, 255, 255), font=font)
        # Save as ICO to bytes
        buf = io.BytesIO()
        img.save(buf, format="ICO")
        FAVICON_ICO_BYTES = buf.getvalue()
        return FAVICON_ICO_BYTES
    except Exception:
        # fallback: serve SVG bytes as ICO response (most browsers will still accept SVG via link rel icons)
        return FAVICON_SVG.encode("utf-8")

HTML_PAGE = """<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1.0' />
  <title>Ajax UCL Qualification Tracker - LIVE</title>
  /favicon.ico
  /favicon.svg
  https://fonts.googleapis.com/css2?family=Teko:wght@300;400;500;600;700&family=Rajdhani:wght@300;400;500;600;700&display=swap
  <style>
    :root{
      --ajax-red:#D2122E;--dark-bg:#0a0a0a;--dark-card:#1a1a1a;--grid-color:rgba(210,18,46,0.12);
      --text-primary:#fff;--text-secondary:#b7b7b7;--success:#00ff88;--warning:#ffaa00;--danger:#ff3333;--neutral:#666
    }
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:'Rajdhani',sans-serif;background:var(--dark-bg);color:var(--text-primary)}
    body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(var(--grid-color) 1px,transparent 1px),linear-gradient(90deg,var(--grid-color) 1px,transparent 1px);background-size:50px 50px;animation:gridMove 20s linear infinite;pointer-events:none;z-index:0}
    @keyframes gridMove{0%{transform:translate(0,0)}100%{transform:translate(50px,50px)}}
    .container{max-width:1200px;margin:0 auto;padding:24px;position:relative;z-index:1}
    header{text-align:center;padding:36px 0;border-bottom:3px solid var(--ajax-red);margin-bottom:28px;position:relative}
    h1{font-family:'Teko',sans-serif;font-size:clamp(2.6rem,8vw,4.8rem);font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px}
    .ajax-text{color:var(--ajax-red);text-shadow:0 0 24px rgba(210,18,46,.65)}
    .subtitle{font-size:1.05rem;color:var(--text-secondary)}
    .live-indicator{display:inline-flex;align-items:center;gap:8px;background:var(--dark-card);padding:8px 14px;border-radius:18px;margin-top:12px;border:1px solid var(--ajax-red)}
    .live-dot{width:10px;height:10px;background:var(--ajax-red);border-radius:50%}
    .status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin:28px 0}
    .status-card{background:var(--dark-card);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:20px}
    .card-label{font-size:.85rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
    .card-value{font-family:'Teko',sans-serif;font-size:2.2rem;font-weight:700}
    .requirements-section,.table-container{background:var(--dark-card);border-radius:12px;padding:24px;margin-bottom:24px;border:1px solid rgba(255,255,255,.08)}
    .section-title{font-family:'Teko',sans-serif;font-size:1.7rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;color:var(--ajax-red)}
    .requirements-counter{font-size:2.4rem;font-family:'Teko',sans-serif;font-weight:700;text-align:center;margin:14px 0;color:var(--ajax-red)}
    .counter-label{font-size:.95rem;color:var(--text-secondary);text-align:center;margin-bottom:20px}
    .requirement-item{background:rgba(255,255,255,.03);border-left:4px solid var(--neutral);padding:12px 16px;margin-bottom:10px;border-radius:6px;display:flex;justify-content:space-between;align-items:center}
    .requirement-item.fulfilled{border-left-color:var(--success);background:rgba(0,255,136,.05)}
    .requirement-item.failed{border-left-color:var(--danger);background:rgba(255,51,51,.05)}
    .requirement-item.pending{border-left-color:var(--warning)}
    .requirement-text{font-size:1rem;font-weight:500;flex:1}
    .requirement-score{font-size:1.05rem;font-weight:700;margin:0 12px;min-width:100px;text-align:center}
    .match-time{font-size:.88rem;color:var(--warning);margin-left:8px}
    .status-badge{padding:4px 10px;border-radius:12px;font-size:.82rem;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
    .status-badge.success{background:var(--success);color:#000}
    .status-badge.danger{background:var(--danger);color:#fff}
    .status-badge.pending{background:var(--warning);color:#000}
    table{width:100%;border-collapse:collapse}
    thead{border-bottom:2px solid var(--ajax-red)}
    th{font-family:'Teko',sans-serif;font-size:1.1rem;font-weight:600;text-transform:uppercase;letter-spacing:1px;padding:10px 8px;text-align:left}
    td{padding:10px 8px;font-size:.98rem}
    tbody tr{border-bottom:1px solid rgba(255,255,255,.05)}
    tbody tr.ajax-row{background:rgba(210,18,46,.15);border:1px solid var(--ajax-red)}
    tbody tr.qualification-line{border-bottom:3px solid var(--success)}
    .refresh-btn{background:var(--ajax-red);color:#fff;border:none;padding:12px 20px;font-family:'Teko',sans-serif;font-size:1.1rem;font-weight:600;text-transform:uppercase;letter-spacing:1px;border-radius:6px;cursor:pointer;margin:16px 0}
    .refresh-btn:disabled{opacity:.6;cursor:not-allowed}
    .last-updated{text-align:center;color:var(--text-secondary);font-size:.9rem;margin-top:8px}
    .api-status{text-align:center;padding:10px;margin:12px 0;border-radius:8px;font-weight:600}
    .api-status.connected{background:rgba(0,255,136,.1);border:1px solid var(--success);color:var(--success)}
    .api-status.error{background:rgba(255,51,51,.1);border:1px solid var(--danger);color:var(--danger)}
    .probability-bar{width:100%;height:8px;background:rgba(255,255,255,.1);border-radius:4px;overflow:hidden;margin-top:8px}
    .probability-fill{height:100%;background:linear-gradient(90deg,var(--danger),var(--warning),var(--success));transition:width .6s ease;border-radius:4px}
  </style>
</head>
<body>
  <div class='container'>
    <header>
      <h1><span class='ajax-text'>AJAX</span> UCL TRACKER</h1>
      <p class='subtitle'>Live Champions League Qualification Monitor</p>
      <div class='live-indicator'><div class='live-dot'></div><span id='liveStatus'>LIVE DATA ACTIVE</span></div>
    </header>

    <div id='apiStatus' class='api-status connected'>Connected - Ready for live data</div>

    <div class='status-grid'>
      <div class='status-card'><div class='card-label'>Current Position</div><div class='card-value' id='currentPosition'>—</div></div>
      <div class='status-card'><div class='card-label'>Points</div><div class='card-value' id='currentPoints'>—</div></div>
      <div class='status-card'><div class='card-label'>Goal Difference</div><div class='card-value' id='goalDifference'>—</div></div>
      <div class='status-card'><div class='card-label'>Qualification Status</div><div class='card-value' style='font-size:1.6rem' id='qualStatus'>—</div>
        <div class='probability-bar'><div id='probabilityBar' class='probability-fill' style='width:0%'></div></div>
      </div>
    </div>

    <div class='requirements-section'>
      <h2 class='section-title'>Path to Top 24: At Least 7 of These Must Happen</h2>
      <div class='requirements-counter'><span id='fulfilledCount'>0</span> / 7</div>
      <div class='counter-label'>Requirements Currently Met (Need 7 to Qualify)</div>
      <div id='requirementsList'></div>
    </div>

    <div class='table-container'>
      <h2 class='section-title'>Champions League Standings (League Phase)</h2>

      <label style="display:flex;align-items:center;gap:8px;margin:4px 0 8px;">
        <input type="checkbox" id="onlyLiveToggle" />
        <span>Only show live matches (disable today fallback)</span>
      </label>

      <button class='refresh-btn' onclick='fetchLiveData()' id='refreshBtn'>REFRESH LIVE DATA</button>
      <div class='last-updated' id='lastUpdated'>Click refresh to load current standings</div>

      <table id='standingsTable'>
        <thead><tr>
          <th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th>
        </tr></thead>
        <tbody id='standingsBody'><tr><td colspan='8' style='text-align:center;padding:24px;'>Click "Refresh Live Data" to load standings</td></tr></tbody>
      </table>
    </div>
  </div>

<script>
  const requirements = [
    { id:1, text:'Ajax MUST beat Olympiacos at home', checkFn: checkFixture('Ajax','Olympiacos') },
    { id:2, text:'Benfica must NOT beat Real Madrid', checkFn: checkNotWin('Benfica','Real Madrid') },
    { id:3, text:'PSV must NOT beat Bayern Munich', checkFn: checkNotWin('PSV','Bayern') },
    { id:4, text:'Bodo/Glimt must NOT beat Atletico Madrid', checkFn: checkNotWin('Bodo','Atletico') },
    { id:5, text:'Club Brugge must NOT beat Marseille', checkFn: checkNotWin('Brugge','Marseille') },
    { id:6, text:'Copenhagen must NOT beat Barcelona', checkFn: checkNotWin('Copenhagen','Barcelona') },
    { id:7, text:'Athletic Bilbao must NOT beat Sporting CP', checkFn: checkNotWin('Athletic','Sporting') },
  ];

  function checkFixture(teamA, teamB){
    return (matches)=>{
      const m = findMatch(matches, teamA, teamB);
      if(!m) return {status:'pending', score:'', time:''};
      const st = m.status;
      const score = formatScore(m);
      const minute = m.minute != null ? String(m.minute) + "'" : '';
      if(st === 'FINISHED') {
        const ajaxWon = teamWon(m, 'Ajax');
        return {status: ajaxWon ? 'fulfilled':'failed', score:score, time:''};
      }
      if(st === 'IN_PLAY' || st === 'PAUSED') return {status:'pending', score:score, time:minute};
      return {status:'pending', score:'', time:''};
    };
  }

  function checkNotWin(teamA, teamB){
    return (matches)=>{
      const m = findMatch(matches, teamA, teamB);
      if(!m) return {status:'pending', score:'', time:''};
      const st = m.status;
      const score = formatScore(m);
      const minute = m.minute != null ? String(m.minute) + "'" : '';
      const aWon = teamWon(m, teamA);
      if(st === 'FINISHED') return {status: aWon ? 'failed':'fulfilled', score:score, time:''};
      if(st === 'IN_PLAY' || st === 'PAUSED') return {status:'pending', score:score, time:minute};
      return {status:'pending', score:'', time:''};
    };
  }

  function teamWon(m, teamName){
    const home = (m.homeTeam || '').toLowerCase();
    const away = (m.awayTeam || '').toLowerCase();
    const t = teamName.toLowerCase();
    const hs = m.homeScore ?? 0;
    const as = m.awayScore ?? 0;
    if(home.includes(t)) return hs > as;
    if(away.includes(t)) return as > hs;
    return false;
  }

  function formatScore(m){ return String(m.homeScore ?? 0) + '-' + String(m.awayScore ?? 0); }

  function findMatch(matches, team1, team2){
    if(!matches || !Array.isArray(matches)) return null;
    const t1 = team1.toLowerCase(); const t2 = team2.toLowerCase();
    return matches.find(x=>{
      const h = (x.homeTeam||'').toLowerCase();
      const a = (x.awayTeam||'').toLowerCase();
      return (h.includes(t1) && a.includes(t2)) || (h.includes(t2) && a.includes(t1));
    }) || null;
  }

  function renderRequirements(matches){
    const container = document.getElementById('requirementsList');
    container.innerHTML='';
    let fulfilled=0;
    requirements.forEach(req=>{
      const r = req.checkFn(matches);
      const item = document.createElement('div');
      item.className = 'requirement-item ' + r.status;
      if(r.status==='fulfilled') fulfilled++;
      let badge = r.status==='fulfilled' ? '<span class="status-badge success">MET</span>' :
                  (r.status==='failed' ? '<span class="status-badge danger">FAILED</span>' :
                                         '<span class="status-badge pending">PENDING</span>');
      const scoreDisplay = r.score ? ('<div class="requirement-score">'+ r.score + (r.time ? ('<span class="match-time">'+ r.time +'</span>'):'') +'</div>') : '';
      item.innerHTML = '<div class="requirement-text">'+ req.text +'</div>'+ scoreDisplay +'<div class="requirement-status">'+ badge +'</div>';
      container.appendChild(item);
    });
    document.getElementById('fulfilledCount').textContent = String(fulfilled);
    const probability = Math.min((fulfilled/7)*100,100);
    document.getElementById('probabilityBar').style.width = String(probability)+'%';
    document.getElementById('qualStatus').textContent = fulfilled>=7 ? 'POSSIBLE!' : (fulfilled>=4 ? 'Still Hope':'Nearly Impossible');
  }

  function renderStandings(fdStandings){
    const tbody = document.getElementById('standingsBody'); tbody.innerHTML='';
    let tableRows = [];
    if(fdStandings && Array.isArray(fdStandings.standings)){
      for(const s of fdStandings.standings){
        if(Array.isArray(s.table)) tableRows = tableRows.concat(s.table);
      }
    }
    const byTeam = new Map();
    for(const row of tableRows){
      const name = row.team && row.team.name ? row.team.name : '';
      if(!name) continue;
      if(!byTeam.has(name) || (row.position && row.position < (byTeam.get(name).position||999))){
        byTeam.set(name, row);
      }
    }
    const rows = Array.from(byTeam.values()).sort((a,b)=> (a.position||999) - (b.position||999));

    rows.forEach(r=>{
      const tr = document.createElement('tr');
      if((r.team && r.team.name || '').includes('Ajax')) tr.classList.add('ajax-row');
      if(r.position === 24) tr.classList.add('qualification-line');
      const gd = r.goalDifference ?? 0;
      tr.innerHTML = '<td><strong>'+ (r.position||'') +'</strong></td>'+
        '<td class="team-name">'+ (r.team && r.team.name ? r.team.name : '') +'</td>'+
        '<td>'+ (r.playedGames ?? '') +'</td>'+
        '<td>'+ (r.won ?? '') +'</td>'+
        '<td>'+ (r.draw ?? '') +'</td>'+
        '<td>'+ (r.lost ?? '') +'</td>'+
        '<td style="color:'+ (gd>=0?'var(--success)':'var(--danger)') +'">'+ (gd>=0?'+':'') + gd +'</td>'+
        '<td><strong>'+ (r.points ?? '') +'</strong></td>';
      tbody.appendChild(tr);
    });

    const ajaxRow = rows.find(r=> r.team && r.team.name && r.team.name.includes('Ajax'));
    if(ajaxRow){
      document.getElementById('currentPosition').textContent = String(ajaxRow.position)+getOrdinal(ajaxRow.position);
      document.getElementById('currentPoints').textContent = String(ajaxRow.points);
      const gd = ajaxRow.goalDifference ?? 0;
      document.getElementById('goalDifference').textContent = gd>=0 ? ('+'+gd) : String(gd);
    }
  }

  function getOrdinal(n){ var s=['th','st','nd','rd']; var v=n%100; return (s[(v-20)%10]||s[v]||s[0]); }

  function updateApiStatus(status,msg){
    const statusDiv=document.getElementById('apiStatus');
    const liveStatus=document.getElementById('liveStatus');
    if(status==='success'){statusDiv.className='api-status connected';statusDiv.textContent=msg||'Data updated successfully';liveStatus.textContent='LIVE DATA ACTIVE';}
    else if(status==='error'){statusDiv.className='api-status error';statusDiv.textContent=msg||'Error fetching data';liveStatus.textContent='CONNECTION ERROR';}
    else {statusDiv.className='api-status connected';statusDiv.textContent='Fetching live data...';liveStatus.textContent='UPDATING...';}
  }

  function isOnlyLiveMode() {
    const el = document.getElementById('onlyLiveToggle');
    return !!(el && el.checked);
  }

  let liveInterval = null;
  const POLL_MS = 30000;

  function startLivePolling() {
    if (liveInterval) clearInterval(liveInterval);
    liveInterval = setInterval(async () => {
      try {
        let matches = [];
        if (isOnlyLiveMode()) {
          const liveRes = await fetch('/api/matches?mode=live');
          if (liveRes.ok) {
            const liveData = await liveRes.json();
            matches = normalizeFdMatches(liveData);
          }
        } else {
          const liveRes = await fetch('/api/matches?mode=live');
          if (liveRes.ok) {
            const liveData = await liveRes.json();
            matches = normalizeFdMatches(liveData);
          }
          if (matches.length === 0) {
            const today = new Date().toISOString().split('T')[0];
            const fxRes = await fetch('/api/matches?dateFrom=' + today + '&dateTo=' + today);
            if (fxRes.ok) {
              const fxData = await fxRes.json();
              matches = normalizeFdMatches(fxData);
            }
          }
        }
        renderRequirements(matches);
        const now = new Date();
        document.getElementById('lastUpdated').textContent = 'Last updated: ' + now.toLocaleTimeString();
      } catch (err) {
        console.error('Polling error:', err);
        updateApiStatus('error', 'Error: ' + err.message);
      }
    }, POLL_MS);
  }

  function stopLivePolling() {
    if (liveInterval) {
      clearInterval(liveInterval);
      liveInterval = null;
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopLivePolling();
    else startLivePolling();
  });

  async function fetchLiveData(){
    const btn=document.getElementById('refreshBtn');
    btn.disabled=true; btn.textContent='FETCHING...'; updateApiStatus('loading');
    try{
      const stRes = await fetch('/api/standings');
      if(!stRes.ok) throw new Error('Standings API error: ' + stRes.status);
      const stData = await stRes.json();
      renderStandings(stData);

      let matches = [];
      if (isOnlyLiveMode()) {
        const liveRes = await fetch('/api/matches?mode=live');
        if(!liveRes.ok) throw new Error('Matches API error (live): ' + liveRes.status);
        const liveData = await liveRes.json();
        matches = normalizeFdMatches(liveData);
      } else {
        const liveRes = await fetch('/api/matches?mode=live');
        if (liveRes.ok){
          const liveData = await liveRes.json();
          matches = normalizeFdMatches(liveData);
        }
        if (matches.length === 0){
          const today = new Date().toISOString().split('T')[0];
          const fxRes = await fetch('/api/matches?dateFrom='+today+'&dateTo='+today);
          if(!fxRes.ok) throw new Error('Matches API error (today): ' + fxRes.status);
          const fxData = await fxRes.json();
          matches = normalizeFdMatches(fxData);
        }
      }
      renderRequirements(matches);
      const now = new Date();
      document.getElementById('lastUpdated').textContent = 'Last updated: ' + now.toLocaleTimeString();
      updateApiStatus('success', 'Live data updated at ' + now.toLocaleTimeString());
      stopLivePolling();
      startLivePolling();
    } catch (error) {
      console.error(error);
      updateApiStatus('error', 'Error: ' + error.message);
    } finally {
      btn.disabled=false; btn.textContent='REFRESH LIVE DATA';
    }
  }

  function normalizeFdMatches(fd){
    if(!fd || !Array.isArray(fd.matches)) return [];
    return fd.matches.map(m=>{
      const status = m.status;
      const homeTeam = m.homeTeam && m.homeTeam.name ? m.homeTeam.name : '';
      const awayTeam = m.awayTeam && m.awayTeam.name ? m.awayTeam.name : '';
      let hs = 0, as = 0;
      if (m.score) {
        if (m.score.fullTime && typeof m.score.fullTime.home === 'number') hs = m.score.fullTime.home;
        else if (m.score.halfTime && typeof m.score.halfTime.home === 'number') hs = m.score.halfTime.home;
        if (m.score.fullTime && typeof m.score.fullTime.away === 'number') as = m.score.fullTime.away;
        else if (m.score.halfTime && typeof m.score.halfTime.away === 'number') as = m.score.halfTime.away;
      }
      const minute = (typeof m.minute === 'number') ? m.minute : null;
      return { status, homeTeam, awayTeam, homeScore: hs, awayScore: as, minute };
    });
  }

  window.addEventListener('load', () => {
    const toggle = document.getElementById('onlyLiveToggle');
    if (toggle) {
      toggle.addEventListener('change', () => {
        stopLivePolling();
        fetchLiveData();
      });
    }
    fetchLiveData();
  });
</script>
</body>
</html>
"""

class FDProxyHandler(BaseHTTPRequestHandler):
    def _write_common_headers(self, status: int, content_type: str):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # --- Favicon routes ---
        if parsed.path == '/favicon.svg':
            self._write_common_headers(200, 'image/svg+xml; charset=utf-8')
            self.wfile.write(FAVICON_SVG.encode('utf-8'))
            return

        if parsed.path == '/favicon.ico':
            ico = _lazy_make_ico()
            self._write_common_headers(200, 'image/x-icon')
            self.wfile.write(ico)
            return

        # Health & root
        if parsed.path == '/healthz':
            self._write_common_headers(200, 'text/plain; charset=utf-8')
            self.wfile.write(b'ok')
            return

        if parsed.path == '/':
            self._write_common_headers(200, 'text/html; charset=utf-8')
            self.wfile.write(HTML_PAGE.encode('utf-8'))
            return

        # API proxy
        if parsed.path == '/api/standings':
            return self.handle_standings()

        if parsed.path == '/api/matches':
            return self.handle_matches(parsed.query)

        self._write_common_headers(404, 'text/plain; charset=utf-8')
        self.wfile.write(b'Not found')

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def _fd_request(self, url):
        if not FD_API_TOKEN:
            self._write_common_headers(500, 'application/json')
            self.wfile.write(b'{"error":"Server not configured: missing FD_TOKEN"}')
            return

        headers = {'X-Auth-Token': FD_API_TOKEN}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                status = resp.getcode()
                self._write_common_headers(status, 'application/json')
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self._write_common_headers(e.code, 'application/json')
            self.wfile.write(e.read() or b'{}')
        except Exception as e:
            self._write_common_headers(502, 'application/json')
            msg = {"error":"Bad Gateway","detail":str(e)}
            self.wfile.write(str(msg).replace("'", "\"").encode('utf-8'))

    def handle_standings(self):
        url = f"{FD_API_BASE}/competitions/{COMPETITION_CODE}/standings"
        return self._fd_request(url)

    def handle_matches(self, query):
        qs = urllib.parse.parse_qs(query)
        mode = (qs.get('mode',[None])[0] or '').lower()
        date_from = qs.get('dateFrom',[None])[0]
        date_to = qs.get('dateTo',[None])[0]
        if mode == 'live':
            url = f"{FD_API_BASE}/competitions/{COMPETITION_CODE}/matches?status=IN_PLAY,PAUSED"
        else:
            params = {}
            if date_from: params['dateFrom'] = date_from
            if date_to: params['dateTo'] = date_to
            qp = f"?{urllib.parse.urlencode(params)}" if params else ''
            url = f"{FD_API_BASE}/competitions/{COMPETITION_CODE}/matches{qp}"
        return self._fd_request(url)

def run_server(port: int):
    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, FDProxyHandler)
    print(f"Ajax UCL Tracker (Football-Data.org) on http://0.0.0.0:{port}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.server_close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Ajax UCL Tracker (Football-Data.org)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not FD_API_TOKEN:
        print('ERROR: Missing Football-Data.org token. Set env FD_TOKEN.')
        sys.exit(1)
    run_server(args.port)