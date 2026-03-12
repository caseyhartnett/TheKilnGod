var config = "";
var all = [];
var table = "";
var lastMessageTs = 0;
var CHART_BG = "#252526";
var CHART_PLOT_BG = "#1e1e1e";
var CHART_GRID = "#3e3e42";
var CHART_TEXT = "#d1d5db";
var COLOR_RED = "#ef4444";
var COLOR_BLUE = "#3b82f6";
var COLOR_GREEN = "#22c55e";

var protocol = "ws:";
if (window.location.protocol === "https:") {
  protocol = "wss:";
}
var host = "" + protocol + "//" + window.location.hostname + ":" + window.location.port;
var ws_status = new WebSocket(host + "/status");
var ws_config = new WebSocket(host + "/config");

ws_status.onmessage = function (e) {
  lastMessageTs = Date.now();
  var x = JSON.parse(e.data);

  if (x.pidstats) {
    x.pidstats.datetime = unix_to_yymmdd_hhmmss(x.pidstats.time);
    x.pidstats.err = x.pidstats.err * -1;
    x.pidstats.out = x.pidstats.out * 100;
    x.pidstats.catching_up = x.catching_up;
    if (x.catching_up === true) {
      x.pidstats.catchingup = x.pidstats.ispoint;
    }
    all.push(x.pidstats);
    if (all.length > 10000) {
      all = all.slice(all.length - 10000);
    }
  }

  document.getElementById("state").innerHTML = "<pre>" + JSON.stringify(x, null, 2) + "</pre>";

  if (table && all.length > 0) {
    table.replaceData(latest(20));
  }

  drawall(all);
  draw_recent(all, 5);
  update_stats(x);
};

ws_config.onopen = function () {
  ws_config.send("GET");
};

ws_config.onmessage = function (e) {
  config = JSON.parse(e.data);
};

create_table(all);

window.setInterval(function () {
  update_stream_status();
}, 2000);

function update_stream_status() {
  var age = lastMessageTs ? ((Date.now() - lastMessageTs) / 1000) : null;
  var el = document.getElementById("stream-status");
  if (!el) {
    return;
  }

  if (age === null) {
    el.innerHTML = "Stream: waiting for data";
    return;
  }
  if (age <= 5) {
    el.innerHTML = "Stream: live";
    return;
  }
  el.innerHTML = "Stream: stale (" + Math.round(age) + "s since last update)";
}

function setText(id, value) {
  var el = document.getElementById(id);
  if (el) {
    el.innerHTML = value;
  }
}

function statusReasonText(x) {
  if (x && x.status_reason_text) {
    return x.status_reason_text;
  }
  if (x && x.last_run_summary && x.last_run_summary.reason_text) {
    return x.last_run_summary.reason_text;
  }
  return "--";
}

function statusReasonKind(x) {
  if (x && x.status_reason_kind) {
    return x.status_reason_kind;
  }
  if (x && x.last_run_summary && x.last_run_summary.reason_kind) {
    return x.last_run_summary.reason_kind;
  }
  return "info";
}

function formatReasonLabel(kind) {
  if (kind === "complete") {
    return "completed";
  }
  if (kind === "error") {
    return "error";
  }
  if (kind === "stopped") {
    return "stopped";
  }
  return "status";
}

function rnd(number) {
  if (!isFinite(number)) {
    return "0.00";
  }
  return Number(number).toFixed(2);
}

function pct(number) {
  if (!isFinite(number)) {
    return "0.00%";
  }
  return Number(number).toFixed(2) + "%";
}

function average(field, minutes, data) {
  if (data.length > 0) {
    var t = data[data.length - 1].time;
    var oldest = t - (60 * minutes);
    var q = "SELECT AVG(" + field + ") as avg FROM ? where time>=" + oldest.toString();
    var avg = alasql(q, [data]);
    return avg[0].avg;
  }
  return 0;
}

function abs_average(minutes, data) {
  var rows = recent_rows(data, minutes);
  if (rows.length === 0) {
    return 0;
  }
  var total = 0;
  for (var i = 0; i < rows.length; i++) {
    total += Math.abs(rows[i].err);
  }
  return total / rows.length;
}

function within_tolerance_pct(minutes, tolerance, data) {
  var rows = recent_rows(data, minutes);
  if (rows.length === 0) {
    return 0;
  }
  var matches = 0;
  for (var i = 0; i < rows.length; i++) {
    if (Math.abs(rows[i].err) <= tolerance) {
      matches += 1;
    }
  }
  return (matches / rows.length) * 100;
}

function within_tolerance_pct_run(tolerance, data) {
  if (data.length === 0) {
    return 0;
  }
  var matches = 0;
  for (var i = 0; i < data.length; i++) {
    if (Math.abs(data[i].err) <= tolerance) {
      matches += 1;
    }
  }
  return (matches / data.length) * 100;
}

function switch_count(minutes, data) {
  var rows = recent_rows(data, minutes);
  if (rows.length <= 1) {
    return 0;
  }
  var count = 0;
  var prev = rows[0].out > 0 ? 1 : 0;
  for (var i = 1; i < rows.length; i++) {
    var now = rows[i].out > 0 ? 1 : 0;
    if (now !== prev) {
      count += 1;
    }
    prev = now;
  }
  return count;
}

function switches_per_hour(data) {
  if (data.length <= 1) {
    return 0;
  }
  var totalSwitches = switch_count(100000, data);
  var spanSeconds = data[data.length - 1].time - data[0].time;
  if (spanSeconds <= 0) {
    return 0;
  }
  return totalSwitches / (spanSeconds / 3600);
}

function duty_cycle(minutes, data) {
  var rows = recent_rows(data, minutes);
  if (rows.length === 0) {
    return 0;
  }
  var sum = 0;
  for (var i = 0; i < rows.length; i++) {
    sum += rows[i].out;
  }
  return sum / rows.length;
}

function overshoot_run(data) {
  if (data.length === 0) {
    return 0;
  }
  var max = 0;
  for (var i = 0; i < data.length; i++) {
    var over = data[i].ispoint - data[i].setpoint;
    if (over > max) {
      max = over;
    }
  }
  return max;
}

function update_stats(x) {
  setText("run-state", x.state || "--");
  setText("run-reason", formatReasonLabel(statusReasonKind(x)) + ": " + statusReasonText(x));

  if (!x.pidstats) {
    return;
  }

  var telemetry = x.telemetry || {};

  setText("error-current", rnd(x.pidstats.err));
  setText("error-1min", rnd(telemetry.error_avg_1m != null ? telemetry.error_avg_1m * -1 : average("err", 1, all)));
  setText("error-5min", rnd(telemetry.error_avg_5m != null ? telemetry.error_avg_5m * -1 : average("err", 5, all)));
  setText("error-15min", rnd(average("err", 15, all)));

  setText("temp", rnd(x.pidstats.ispoint));
  setText("target", rnd(x.pidstats.setpoint));
  setText("heat-pct", rnd(x.pidstats.out));

  var catchup = telemetry.time_catching_up_pct_run != null ? telemetry.time_catching_up_pct_run : percent_catching_up(all);
  setText("catching-up", rnd(catchup));

  var mae5m = telemetry.error_abs_avg_5m != null ? telemetry.error_abs_avg_5m : abs_average(5, all);
  var within5m = telemetry.within_5deg_pct_5m != null ? telemetry.within_5deg_pct_5m : within_tolerance_pct(5, 5, all);
  var withinRun = telemetry.within_5deg_pct_run != null ? telemetry.within_5deg_pct_run : within_tolerance_pct_run(5, all);
  var switches5m = telemetry.switches_5m != null ? telemetry.switches_5m : switch_count(5, all);
  var switchesHour = telemetry.switches_per_hour_run != null ? telemetry.switches_per_hour_run : switches_per_hour(all);
  var duty5m = telemetry.duty_cycle_5m != null ? telemetry.duty_cycle_5m : duty_cycle(5, all);
  var overshoot = telemetry.overshoot_max_run != null ? telemetry.overshoot_max_run : overshoot_run(all);
  var sensorErr = telemetry.sensor_error_rate_5m != null ? telemetry.sensor_error_rate_5m : 0;

  setText("mae-5m", rnd(mae5m));
  setText("within-5m", pct(within5m));
  setText("within-run", pct(withinRun));
  setText("switches-5m", rnd(switches5m));
  setText("switches-hour", rnd(switchesHour));
  setText("duty-5m", pct(duty5m));
  setText("overshoot-run", rnd(overshoot));
  setText("sensor-error", pct(sensorErr));
}

function drawall(data) {
  draw_temps(data);
  draw_error(data);
  draw_heat(data);
  draw_p(data);
  draw_i(data);
  draw_d(data);
}

function draw_recent(data, minutes) {
  var rows = recent_rows(data, minutes);
  draw_error_recent(rows);
  draw_switching_recent(rows);
}

function draw_heat(data) {
  var traces = [];
  var rows = alasql("SELECT datetime, out from ?", [data]);

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "out"),
    name: "heat",
    mode: "lines",
    line: { color: COLOR_RED, width: 2 }
  });

  var spot = document.getElementById("heat");
  Plotly.newPlot(spot, traces, chartLayout("Heating Percent", true), { displayModeBar: false });
}

function draw_p(data) {
  var traces = [];
  var rows = alasql("SELECT datetime, p from ?", [data]);

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "p"),
    name: "p",
    mode: "lines",
    line: { color: COLOR_BLUE, width: 2 }
  });

  var spot = document.getElementById("p");
  Plotly.newPlot(spot, traces, chartLayout("Proportional", true), { displayModeBar: false });
}

function draw_i(data) {
  var traces = [];
  var rows = alasql("SELECT datetime, i from ?", [data]);

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "i"),
    name: "i",
    mode: "lines",
    line: { color: COLOR_BLUE, width: 2 }
  });

  var spot = document.getElementById("i");
  Plotly.newPlot(spot, traces, chartLayout("Integral", true), { displayModeBar: false });
}

function draw_d(data) {
  var traces = [];
  var rows = alasql("SELECT datetime, d from ?", [data]);

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "d"),
    name: "d",
    mode: "lines",
    line: { color: COLOR_BLUE, width: 2 }
  });

  var spot = document.getElementById("d");
  Plotly.newPlot(spot, traces, chartLayout("Derivative", true), { displayModeBar: false });
}

function draw_error(data) {
  var traces = [];
  var rows = alasql("SELECT datetime, err from ?", [data]);

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "err"),
    name: "error",
    mode: "lines",
    line: { color: COLOR_RED, width: 2 }
  });

  var spot = document.getElementById("error");
  Plotly.newPlot(spot, traces, chartLayout("Error", true), { displayModeBar: false });
}

function draw_error_recent(rows) {
  var traces = [];

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "err"),
    name: "error",
    mode: "lines",
    line: { color: COLOR_RED, width: 2 }
  });

  var spot = document.getElementById("error-5m");
  var layout = chartLayout("Error (Last 5 Minutes)", false);
  layout.yaxis.zeroline = true;
  layout.yaxis.zerolinewidth = 2;
  layout.yaxis.zerolinecolor = CHART_GRID;
  Plotly.newPlot(spot, traces, layout, { displayModeBar: false });
}

function draw_switching_recent(rows) {
  var i;
  var points = [];
  for (i = 0; i < rows.length; i++) {
    points.push({ datetime: rows[i].datetime, heatOn: rows[i].out > 0 ? 1 : 0 });
  }

  var traces = [];
  traces.push({
    x: unpack(points, "datetime"),
    y: unpack(points, "heatOn"),
    name: "heat_on",
    mode: "lines",
    line: { color: COLOR_GREEN, width: 2, shape: "hv" }
  });

  var spot = document.getElementById("switching-5m");
  var layout = chartLayout("Relay On/Off (Last 5 Minutes)", false);
  layout.yaxis.range = [-0.1, 1.1];
  layout.yaxis.tickvals = [0, 1];
  layout.yaxis.ticktext = ["OFF", "ON"];
  Plotly.newPlot(spot, traces, layout, { displayModeBar: false });
}

function draw_temps(data) {
  var traces = [];
  var rows = alasql("SELECT datetime, ispoint, setpoint, catchingup from ?", [data]);

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "setpoint"),
    name: "target",
    mode: "lines",
    line: { color: COLOR_BLUE, width: 2 }
  });

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "ispoint"),
    name: "temp",
    mode: "lines",
    line: { color: COLOR_RED, width: 2 }
  });

  traces.push({
    x: unpack(rows, "datetime"),
    y: unpack(rows, "catchingup"),
    name: "catchup",
    mode: "markers",
    marker: { color: COLOR_GREEN, width: 3 }
  });

  var spot = document.getElementById("temps");
  Plotly.newPlot(spot, traces, chartLayout("Temperature and Target", true), { displayModeBar: false });
}

function chartLayout(title, showlegend) {
  return {
    title: { text: title, font: { color: CHART_TEXT } },
    showlegend: showlegend,
    paper_bgcolor: CHART_BG,
    plot_bgcolor: CHART_PLOT_BG,
    font: { color: CHART_TEXT },
    xaxis: {
      gridcolor: CHART_GRID,
      zerolinecolor: CHART_GRID,
      color: CHART_TEXT
    },
    yaxis: {
      gridcolor: CHART_GRID,
      zerolinecolor: CHART_GRID,
      color: CHART_TEXT
    },
    margin: { l: 55, r: 24, t: 44, b: 44 }
  };
}

function unpack(rows, key) {
  return rows.map(function (row) {
    return row[key];
  });
}

function unix_to_yymmdd_hhmmss(t) {
  var date = new Date(t * 1000);
  var newd = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return newd.toISOString().replace("T", " ").substring(0, 19);
}

function latest(n) {
  var sql = "select * from ? order by time desc limit " + n;
  return alasql(sql, [all]);
}

function recent_rows(data, minutes) {
  if (data.length === 0) {
    return [];
  }
  var cutoff = data[data.length - 1].time - (minutes * 60);
  var out = [];
  for (var i = 0; i < data.length; i++) {
    if (data[i].time >= cutoff) {
      out.push(data[i]);
    }
  }
  return out;
}

function percent_catching_up(data) {
  var sql = "select sum(timeDelta) as slip from ? where catching_up=true";
  var a = alasql(sql, [data]);
  var slip = a[0] && a[0].slip ? a[0].slip : 0;
  sql = "select sum(timeDelta) as all_time from ?";
  var b = alasql(sql, [data]);
  var total = b[0] && b[0].all_time ? b[0].all_time : 0;
  if (!total) {
    return 0;
  }
  return (slip / total) * 100;
}

function create_table(data) {
  table = new Tabulator("#state-table", {
    height: 300,
    data: data,
    layout: "fitColumns",
    headerVisible: true,
    movableColumns: false,
    cssClass: "tabulator-dark",
    columns: [
      { title: "DateTime", field: "datetime" },
      { title: "Target", field: "setpoint" },
      { title: "Temp", field: "ispoint" },
      { title: "Error", field: "err" },
      { title: "P", field: "p" },
      { title: "I", field: "i" },
      { title: "D", field: "d" },
      { title: "Heat", field: "out" },
      { title: "Catching Up", field: "catching_up" },
      { title: "Time Delta", field: "timeDelta" }
    ]
  });
}

function csv_string() {
  table.download("csv", "kiln-state.csv");
}
