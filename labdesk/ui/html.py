"""HTML shell.

The topbar follows TubeForge: wordmark, then the tally lamp sized to the
wordmark's cap height so a running job is visible from across the room.
"""

SHELL = r"""<!doctype html>
<html lang="en" data-theme="daylight" data-type="site"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LabDesk | Rasa Khosrofar, M.D.</title>
<meta name="description" content="LabDesk: a research workbench for literature searches, study screening, bias assessment and statistical analysis, with decisions and outputs kept together. Working demo.">
<link rel="stylesheet" href="/static/app.css">
</head><body>
<div id="app">

  <div id="topbar">
    <div class="wordmark">
      <span class="tally-lamp" id="lamp"></span>
      <b>Lab<em>Desk</em></b>
      <span class="ver" id="version"></span>
    </div>
    <div class="topbar-path" id="ds-chip" title="Active dataset">no dataset</div>
    <div class="spacer"></div>
    <button class="topbar-btn" id="theme-toggle" title="Daylight or bench">theme</button>
  </div>

  <div id="body">
    <div id="rail"></div>
    <div id="work"><div class="empty">Loading</div></div>
    <div id="inspector"></div>
  </div>

  <div id="tip" hidden></div>

  <div id="dock">
    <span class="dot" id="dock-dot"></span>
    <span id="dock-status">idle</span>
    <span class="spacer"></span>
    <span id="dock-jobs"></span>
  </div>

</div>
<script src="/static/app.js"></script>
</body></html>
"""


def page():
    return SHELL