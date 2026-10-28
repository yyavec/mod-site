// 사이트 전체 관리자 (10-22 주인님): 고정 링크 <아무 페이지>#k=<관리자 키> 를 한 번 열면 이 기기가 관리자로 기억된다
// - 키는 localStorage 'deck-admin-key' (트레이너 배틀·추억 저장소·팀전이 같이 씀), 주소에서는 바로 지운다
// - 키가 없는 기기는 <아무 페이지>?admin 으로 열면 구글 로그인으로 관리자가 된다 (?adminkey 는 키 직접 입력)
// - 관리자면 왼쪽 아래에 👑 관리자 버튼과 메뉴가 뜬다
(function(){
  var KEYN = 'deck-admin-key';
  var m = /(?:^#|&)k=([^&]+)/.exec(location.hash);
  if (m) {
    try { localStorage.setItem(KEYN, decodeURIComponent(m[1])); } catch (e) {}
    history.replaceState(null, '', location.pathname + location.search);
  }
  var key = '';
  try { key = localStorage.getItem(KEYN) || ''; } catch (e) {}
  // 10-28: 키가 없는 기기(휴대폰 등)는 주소 끝에 ?admin → 구글 로그인 페이지(Apps Script, 액세스 '나만')가 #k=키 로 돌려보낸다
  //        ?adminkey 는 예전처럼 키를 직접 넣는 창
  var LOGIN = 'https://script.google.com/macros/s/AKfycbxvgX2nzOL9jyhZh1BS73gF0rbYuEu1FNrmGybEp9820QtEY-z5GiUCfGgqBh4gd_Bz/exec';
  if (!key && /[?&]admin(?:[=&]|$)/.test(location.search)) {
    location.replace(LOGIN + '?to=' + encodeURIComponent(location.pathname.split('/').pop()));
    return;
  }
  if (!key && /[?&]adminkey(?:[=&]|$)/.test(location.search)) {
    key = (prompt('관리자 키를 넣어 주세요 (이 기기에 기억돼요)') || '').trim();
    if (key) { try { localStorage.setItem(KEYN, key); } catch (e) {} }
    history.replaceState(null, '', location.pathname + location.search.replace(/[?&]adminkey(=[^&]*)?/, '').replace(/^&/, '?') + location.hash);
  }
  window.SITE_ADMIN_KEY = key;
  if (!key) return;
  document.documentElement.setAttribute('data-admin', '');
  function ui(){
    var css = document.createElement('style');
    css.textContent = '.adm-fab{position:fixed;left:14px;bottom:max(14px, env(safe-area-inset-bottom));z-index:2147483000;font:700 13px/1 "Pretendard Variable",Pretendard,sans-serif}'
      + '.adm-fab>button{display:inline-flex;align-items:center;gap:6px;padding:10px 14px;border:1px solid rgba(255,203,5,.6);border-radius:999px;background:rgba(20,16,32,.92);color:#ffe27a;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.4);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}'
      + '.adm-menu{position:absolute;left:0;bottom:48px;min-width:230px;padding:6px;border-radius:14px;background:#17122a;border:1px solid rgba(255,255,255,.12);box-shadow:0 14px 40px rgba(0,0,0,.5)}'
      + '.adm-menu[hidden]{display:none}.adm-menu a,.adm-menu button{display:block;width:100%;padding:11px 12px;border:0;border-radius:10px;background:none;color:#f3f1f7;text-align:left;text-decoration:none;font-size:14px;font-weight:600;line-height:1.2;cursor:pointer}'
      + '.adm-menu a:hover,.adm-menu button:hover{background:rgba(255,255,255,.08)}.adm-menu .off{color:#ff8a80}.adm-menu small{display:block;padding:8px 12px 4px;color:#8c84a3;font-weight:600;font-size:11px;letter-spacing:.08em}';
    document.head.appendChild(css);
    var box = document.createElement('div');
    box.className = 'adm-fab';
    box.innerHTML = '<button type="button" aria-expanded="false">👑 관리자</button><div class="adm-menu" hidden>'
      + '<small>관리자 메뉴</small>'
      + '<a href="team.html#goal">⚔️ 팀전 — 목표덱·팀 이름 관리</a>'
      + '<a href="memories.html">📸 추억 저장소 — 사진 정리</a>'
      + '<a href="./?battle&deckadmin">🏆 1차 트레이너 배틀 — 덱·대진표</a>'
      + '<button type="button" class="off">관리자 끄기 (이 기기)</button></div>';
    document.body.appendChild(box);
    var b = box.querySelector('button'), menu = box.querySelector('.adm-menu');
    b.addEventListener('click', function(){ menu.hidden = !menu.hidden; b.setAttribute('aria-expanded', String(!menu.hidden)); });
    box.querySelector('.off').addEventListener('click', function(){
      if (!confirm('이 기기에서 관리자를 끌까요? 다시 켜려면 관리자 링크를 열면 돼요.')) return;
      try { localStorage.removeItem(KEYN); } catch (e) {}
      location.reload();
    });
    document.addEventListener('click', function(e){ if (!box.contains(e.target)) { menu.hidden = true; b.setAttribute('aria-expanded', 'false'); } });
  }
  if (document.body) ui(); else document.addEventListener('DOMContentLoaded', ui);
})();
