var state = "IDLE";
var state_last = "";
var graph = [ 'profile', 'live'];
var points = [];
var profiles = [];
var time_mode = 0;
var selected_profile = 0;
var selected_profile_name = 'cone-05-long-bisque.json';
var temp_scale = "c";
var time_scale_slope = "s";
var time_scale_profile = "h";
var time_scale_long = "Seconds";
var temp_scale_display = "C";
var kwh_rate = 0.26;
var currency_type = "EUR";

var protocol = 'ws:';
if (window.location.protocol == 'https:') {
    protocol = 'wss:';
}
var host = "" + protocol + "//" + window.location.hostname + ":" + window.location.port;
var ws_status = new WebSocket(host+"/status");
var ws_control = new WebSocket(host+"/control");
var ws_config = new WebSocket(host+"/config");
var ws_storage = new WebSocket(host+"/storage");


if(window.webkitRequestAnimationFrame) window.requestAnimationFrame = window.webkitRequestAnimationFrame;

graph.profile =
{
    label: "Profile",
    data: [],
    points: { show: false },
    color: "#75890c",
    draggable: false
};

graph.live =
{
    label: "Live",
    data: [],
    points: { show: false },
    color: "#d8d3c5",
    draggable: false
};


function updateProfile(id)
{
    id = parseInt(id, 10);
    if (isNaN(id) || id < 0 || id >= profiles.length) {
        return;
    }
    selected_profile = id;
    selected_profile_name = profiles[id].name;
    var job_seconds = profiles[id].data.length === 0 ? 0 : parseInt(profiles[id].data[profiles[id].data.length-1][0]);
    var kwh = (3850*job_seconds/3600/1000).toFixed(2);
    var cost =  (kwh*kwh_rate).toFixed(2);
    var job_time = new Date(job_seconds * 1000).toISOString().substr(11, 8);
    $('#sel_prof').html(profiles[id].name);
    $('#sel_prof_eta').html(job_time);
    $('#sel_prof_cost').html(kwh + ' kWh ('+ currency_type +': '+ cost +')');
    graph.profile.data = profiles[id].data;
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ] , getOptions());
    updateSelectedProfilePreview(profiles[id], job_time);
}

function formatDisplayTemp(value) {
    if (typeof value === 'undefined' || value === null || isNaN(value)) {
        return '--';
    }
    return parseInt(value, 10) + '°' + temp_scale_display;
}

function updateSelectedProfilePreview(profile, runtimeText)
{
    if (!profile) {
        return;
    }
    var points = profile.data || [];
    var startTemp = points.length ? points[0][1] : null;
    var endTemp = points.length ? points[points.length-1][1] : null;
    var peakTemp = null;
    for (var i=0; i<points.length; i++) {
        if (peakTemp === null || points[i][1] > peakTemp) {
            peakTemp = points[i][1];
        }
    }

    $('#preview_profile_name').text(profile.name || '---');
    $('#preview_runtime').text(runtimeText || '--:--:--');
    $('#preview_points').text(points.length);
    $('#preview_start_temp').text(formatDisplayTemp(startTemp));
    $('#preview_peak_temp').text(formatDisplayTemp(peakTemp));
    $('#preview_end_temp').text(formatDisplayTemp(endTemp));
}

function deleteProfile()
{
    var profile = { "type": "profile", "data": "", "name": selected_profile_name };
    var delete_struct = { "cmd": "DELETE", "profile": profile };

    var delete_cmd = JSON.stringify(delete_struct);
    console.log("Delete profile:" + selected_profile_name);

    ws_storage.send(delete_cmd);

    ws_storage.send('GET');
    selected_profile_name = profiles[0].name;

    state="IDLE";
    $('#edit').hide();
    $('#profile_selector').show();
    $('#btn_controls').show();
    $('#status').slideDown();
    $('#profile_table').slideUp();
    $('#e2').select2('val', 0);
    graph.profile.points.show = false;
    graph.profile.draggable = false;
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
}


function updateProgress(percentage)
{
    if(state=="RUNNING")
    {
        if(percentage > 100) percentage = 100;
        $('#progressBar').css('width', percentage+'%');
        if(percentage>5) $('#progressBar').html(parseInt(percentage)+'%');
    }
    else
    {
        $('#progressBar').css('width', 0+'%');
        $('#progressBar').html('');
    }
}

function updateProfileTable()
{
    var dps = 0;
    var slope = "";
    var color = "";

    var html = '<h3>Schedule Points</h3><div class="table-responsive" style="scroll: none"><table class="table table-striped">';
        html += '<tr><th>#</th><th>Target Time in ' + time_scale_long+ '</th><th>Target Temperature in °'+temp_scale_display+'</th><th>Slope in &deg;'+temp_scale_display+'/'+time_scale_slope+'</th><th></th></tr>';

    for(var i=0; i<graph.profile.data.length;i++)
    {

        if (i>=1) dps =  ((graph.profile.data[i][1]-graph.profile.data[i-1][1])/(graph.profile.data[i][0]-graph.profile.data[i-1][0]) * 10) / 10;
        if (dps  > 0) { slope = "up";     color="rgba(206, 5, 5, 1)"; } else
        if (dps  < 0) { slope = "down";   color="rgba(23, 108, 204, 1)"; dps *= -1; } else
        if (dps == 0) { slope = "right";  color="grey"; }

        html += '<tr><td><h4>' + (i+1) + '</h4></td>';
        html += '<td><input type="text" class="form-control profile-table-time" id="profiletable-0-'+i+'" value="'+ timeProfileFormatter(graph.profile.data[i][0],true) + '" /></td>';
        html += '<td><input type="text" class="form-control profile-table-temp" id="profiletable-1-'+i+'" value="'+ graph.profile.data[i][1] + '" /></td>';
        html += '<td><div class="input-group"><span class="glyphicon glyphicon-circle-arrow-' + slope + ' input-group-addon ds-trend" style="background: '+color+'"></span><input type="text" class="form-control ds-input profile-table-slope" readonly value="' + formatDPS(dps) + '" /></div></td>';
        html += '<td>&nbsp;</td></tr>';
    }

    html += '</table></div>';

    $('#profile_table').html(html);

    //Link table to graph
    $("#profile_table .form-control").change(function(e)
        {
            var id = $(this)[0].id; //e.currentTarget.attributes.id
            var value = parseInt($(this)[0].value);
            var fields = id.split("-");
            var col = parseInt(fields[1]);
            var row = parseInt(fields[2]);

            if (graph.profile.data.length > 0) {
            if (col == 0) {
                graph.profile.data[row][col] = timeProfileFormatter(value,false);
            }
            else {
                graph.profile.data[row][col] = value;
            }

            graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
            }
            updateProfileTable();

        });
}

function setBuilderUnits() {
    $('#builder_unit_start').text(temp_scale_display);
    $('#builder_unit_target').text(temp_scale_display);
    $('#builder_unit_rate').text(temp_scale_display);
}

function addBuilderRow(target, rate, hold) {
    var t = (typeof target !== 'undefined') ? target : '';
    var r = (typeof rate !== 'undefined') ? rate : '';
    var h = (typeof hold !== 'undefined') ? hold : 0;
    var row = ''
        + '<tr>'
        + '<td><input type="number" class="form-control builder-target" value="' + t + '" /></td>'
        + '<td><input type="number" class="form-control builder-rate" value="' + r + '" min="0" /></td>'
        + '<td><input type="number" class="form-control builder-hold" value="' + h + '" min="0" /></td>'
        + '<td><button type="button" class="btn btn-xs btn-danger" onclick="$(this).closest(\'tr\').remove();">Remove</button></td>'
        + '</tr>';
    $('#builder_segments_body').append(row);
}

function removeBuilderRow() {
    var rows = $('#builder_segments_body tr');
    if (rows.length > 0) {
        rows.last().remove();
    }
}

function initializeBuilderDefaults() {
    if ($('#builder_segments_body tr').length > 0) {
        return;
    }
    addBuilderRow(250, 200, 0);
    addBuilderRow(1000, 350, 20);
    addBuilderRow(1830, 150, 15);
    addBuilderRow(1400, 300, 0);
}

function applyBuilderSchedule() {
    var startTemp = parseFloat($('#builder_start_temp').val());
    if (isNaN(startTemp)) {
        $.bootstrapGrowl("<span class=\"glyphicon glyphicon-exclamation-sign\"></span> Enter a valid start temperature.", {
            ele: 'body', type: 'error', offset: {from: 'top', amount: 250}, align: 'center', width: 385, delay: 3500, allow_dismiss: true, stackup_spacing: 10
        });
        return;
    }

    var pointsData = [[0, Math.round(startTemp)]];
    var currentTemp = startTemp;
    var currentTime = 0;
    var badRow = false;

    $('#builder_segments_body tr').each(function() {
        var target = parseFloat($(this).find('.builder-target').val());
        var ramp = parseFloat($(this).find('.builder-rate').val());
        var hold = parseFloat($(this).find('.builder-hold').val());

        if (isNaN(target)) {
            return;
        }
        if (isNaN(hold) || hold < 0) {
            hold = 0;
        }

        if (target !== currentTemp) {
            if (isNaN(ramp) || ramp <= 0) {
                badRow = true;
                return false;
            }
            var rampSeconds = Math.abs(target - currentTemp) / ramp * 3600.0;
            currentTime += rampSeconds;
            pointsData.push([Math.round(currentTime), Math.round(target)]);
            currentTemp = target;
        }

        if (hold > 0) {
            currentTime += hold * 60.0;
            pointsData.push([Math.round(currentTime), Math.round(target)]);
        }
    });

    if (badRow || pointsData.length < 2) {
        $.bootstrapGrowl("<span class=\"glyphicon glyphicon-exclamation-sign\"></span> Builder needs at least one valid segment with ramp rate.", {
            ele: 'body', type: 'error', offset: {from: 'top', amount: 250}, align: 'center', width: 430, delay: 4000, allow_dismiss: true, stackup_spacing: 10
        });
        return;
    }

    graph.profile.data = pointsData;
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
    updateProfileTable();
    $('#profile_table').slideDown();
    $('.schedule-tabs a[href="#schedule_points_tab"]').tab('show');
}

function timeProfileFormatter(val, down) {
    var rval = val
    switch(time_scale_profile){
        case "m":
            if (down) {rval = val / 60;} else {rval = val * 60;}
            break;
        case "h":
            if (down) {rval = val / 3600;} else {rval = val * 3600;}
            break;
    }
    return Math.round(rval);
}

function formatDPS(val) {
    var tval = val;
    if (time_scale_slope == "m") {
        tval = val * 60;
    }
    if (time_scale_slope == "h") {
        tval = (val * 60) * 60;
    }
    return Math.round(tval);
}

function hazardTemp(){

    if (temp_scale == "f") {
        return (1500 * 9 / 5) + 32
    }
    else {
        return 1500
    }
}

function timeTickFormatter(val,axis)
{
// hours
if(axis.max>3600) {
  //var hours = Math.floor(val / (3600));
  //return hours;
  return Math.floor(val/3600);
  }

// minutes
if(axis.max<=3600) {
  return Math.floor(val/60);
  }

// seconds
if(axis.max<=60) {
  return val;
  }
}

function runTask()
{
    var cmd =
    {
        "cmd": "RUN",
        "profile": profiles[selected_profile]
    }

    graph.live.data = [];
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ] , getOptions());

    ws_control.send(JSON.stringify(cmd));

}

function runTaskSimulation()
{
    var cmd =
    {
        "cmd": "SIMULATE",
        "profile": profiles[selected_profile]
    }

    graph.live.data = [];
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ] , getOptions());

    ws_control.send(JSON.stringify(cmd));

}


function abortTask()
{
    var cmd = {"cmd": "STOP"};
    ws_control.send(JSON.stringify(cmd));
}

function enterNewMode()
{
    state="EDIT"
    $('#status').slideUp();
    $('#edit').show();
    $('#profile_selector').hide();
    $('#selected_profile_preview').hide();
    $('#btn_controls').hide();
    $('#form_profile_name').attr('value', '');
    $('#form_profile_name').attr('placeholder', 'Please enter a name');
    graph.profile.points.show = true;
    graph.profile.draggable = true;
    graph.profile.data = [];
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
    initializeBuilderDefaults();
    setBuilderUnits();
    $('.schedule-tabs a[href="#schedule_builder_tab"]').tab('show');
    updateProfileTable();
}

function enterEditMode()
{
    state="EDIT"
    $('#status').slideUp();
    $('#edit').show();
    $('#profile_selector').hide();
    $('#selected_profile_preview').hide();
    $('#btn_controls').hide();
    console.log(profiles);
    $('#form_profile_name').val(profiles[selected_profile].name);
    graph.profile.points.show = true;
    graph.profile.draggable = true;
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
    initializeBuilderDefaults();
    setBuilderUnits();
    $('.schedule-tabs a[href="#schedule_points_tab"]').tab('show');
    updateProfileTable();
    toggleTable();
}

function leaveEditMode()
{
    selected_profile_name = $('#form_profile_name').val();
    ws_storage.send('GET');
    state="IDLE";
    $('#edit').hide();
    $('#profile_selector').show();
    $('#selected_profile_preview').show();
    $('#btn_controls').show();
    $('#status').slideDown();
    $('#profile_table').slideUp();
    graph.profile.points.show = false;
    graph.profile.draggable = false;
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
    $('.schedule-tabs a[href="#schedule_points_tab"]').tab('show');
}

function newPoint()
{
    if(graph.profile.data.length > 0)
    {
        var pointx = parseInt(graph.profile.data[graph.profile.data.length-1][0])+15;
    }
    else
    {
        var pointx = 0;
    }
    graph.profile.data.push([pointx, Math.floor((Math.random()*230)+25)]);
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
    updateProfileTable();
}

function delPoint()
{
    graph.profile.data.splice(-1,1)
    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ], getOptions());
    updateProfileTable();
}

function toggleTable()
{
    if($('#profile_table').css('display') == 'none')
    {
        $('#profile_table').slideDown();
    }
    else
    {
        $('#profile_table').slideUp();
    }
}

function saveProfile()
{
    name = $('#form_profile_name').val();
    var rawdata = graph.plot.getData()[0].data
    var data = [];
    var last = -1;

    for(var i=0; i<rawdata.length;i++)
    {
        if(rawdata[i][0] > last)
        {
          data.push([rawdata[i][0], rawdata[i][1]]);
        }
        else
        {
          $.bootstrapGrowl("<span class=\"glyphicon glyphicon-exclamation-sign\"></span> <b>ERROR 88:</b><br/>An oven is not a time-machine", {
            ele: 'body', // which element to append to
            type: 'alert', // (null, 'info', 'error', 'success')
            offset: {from: 'top', amount: 250}, // 'top', or 'bottom'
            align: 'center', // ('left', 'right', or 'center')
            width: 385, // (integer, or 'auto')
            delay: 5000,
            allow_dismiss: true,
            stackup_spacing: 10 // spacing between consecutively stacked growls.
          });

          return false;
        }

        last = rawdata[i][0];
    }

    var profile = { "type": "profile", "data": data, "name": name }
    var put = { "cmd": "PUT", "profile": profile }

    var put_cmd = JSON.stringify(put);

    ws_storage.send(put_cmd);

    leaveEditMode();
}

function get_tick_size() {
//switch(time_scale_profile){
//  case "s":
//    return 1;
//  case "m":
//    return 60;
//  case "h":
//    return 3600;
//  }
return 3600;
}

function getOptions()
{

  var options =
  {

    series:
    {
        lines:
        {
            show: true
        },

        points:
        {
            show: true,
            radius: 5,
            symbol: "circle"
        },

        shadowSize: 3

    },

	xaxis:
    {
      min: 0,
      tickColor: 'rgba(216, 211, 197, 0.2)',
      tickFormatter: timeTickFormatter,
      tickSize: get_tick_size(),
      font:
      {
        size: 14,
        lineHeight: 14,        weight: "normal",
        family: "Digi",
        variant: "small-caps",
        color: "rgba(216, 211, 197, 0.85)"
      }
	},

	yaxis:
    {
      min: 0,
      tickDecimals: 0,
      draggable: false,
      tickColor: 'rgba(216, 211, 197, 0.2)',
      font:
      {
        size: 14,
        lineHeight: 14,
        weight: "normal",
        family: "Digi",
        variant: "small-caps",
        color: "rgba(216, 211, 197, 0.85)"
      }
	},

	grid:
    {
	  color: 'rgba(216, 211, 197, 0.55)',
      borderWidth: 1,
      labelMargin: 10,
      mouseActiveRadius: 50
	},

    legend:
    {
      show: false
    }
  }

  return options;

}



$(document).ready(function()
{

    if(!("WebSocket" in window))
    {
        $('#chatLog, input, button, #examples').fadeOut("fast");
        $('<p>Oh no, you need a browser that supports WebSockets. How about <a href="http://www.google.com/chrome">Google Chrome</a>?</p>').appendTo('#container');
    }
    else
    {

        // Status Socket ////////////////////////////////

        ws_status.onopen = function()
        {
            console.log("Status Socket has been opened");

//            $.bootstrapGrowl("<span class=\"glyphicon glyphicon-exclamation-sign\"></span>Getting data from server",
//            {
//            ele: 'body', // which element to append to
//            type: 'success', // (null, 'info', 'error', 'success')
//            offset: {from: 'top', amount: 250}, // 'top', or 'bottom'
//            align: 'center', // ('left', 'right', or 'center')
//            width: 385, // (integer, or 'auto')
//            delay: 2500,
//            allow_dismiss: true,
//            stackup_spacing: 10 // spacing between consecutively stacked growls.
//            });
        };

        ws_status.onclose = function()
        {
            $.bootstrapGrowl("<span class=\"glyphicon glyphicon-exclamation-sign\"></span> <b>ERROR 1:</b><br/>Status Websocket not available", {
            ele: 'body', // which element to append to
            type: 'error', // (null, 'info', 'error', 'success')
            offset: {from: 'top', amount: 250}, // 'top', or 'bottom'
            align: 'center', // ('left', 'right', or 'center')
            width: 385, // (integer, or 'auto')
            delay: 5000,
            allow_dismiss: true,
            stackup_spacing: 10 // spacing between consecutively stacked growls.
          });
        };

        ws_status.onmessage = function(e)
        {
            x = JSON.parse(e.data);
            if (x.type == "backlog")
            {
                if (x.profile)
                {
                    selected_profile_name = x.profile.name;
                    $.each(profiles,  function(i,v) {
                        if(v.name == x.profile.name) {
                            updateProfile(i);
                            $('#e2').select2('val', i);
                        }
                    });
                }

                $.each(x.log, function(i,v) {
                    graph.live.data.push([v.runtime, v.temperature]);
                    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ] , getOptions());
                });
            }

            if(state!="EDIT")
            {
                state = x.state;
                if (state!=state_last)
                {
                    if(state_last == "RUNNING" && state != "PAUSED" )
                    {
			console.log(state);
                        $('#target_temp').html('---');
                        updateProgress(0);
                        $.bootstrapGrowl("<span class=\"glyphicon glyphicon-exclamation-sign\"></span> <b>Run completed</b>", {
                        ele: 'body', // which element to append to
                        type: 'success', // (null, 'info', 'error', 'success')
                        offset: {from: 'top', amount: 250}, // 'top', or 'bottom'
                        align: 'center', // ('left', 'right', or 'center')
                        width: 385, // (integer, or 'auto')
                        delay: 0,
                        allow_dismiss: true,
                        stackup_spacing: 10 // spacing between consecutively stacked growls.
                        });
                    }
                }

                if(state=="RUNNING")
                {
                    $("#nav_start").hide();
                    $("#nav_stop").show();

                    graph.live.data.push([x.runtime, x.temperature]);
                    graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ] , getOptions());

                    left = parseInt(x.totaltime-x.runtime);
                    eta = new Date(left * 1000).toISOString().substr(11, 8);

                    updateProgress(parseFloat(x.runtime)/parseFloat(x.totaltime)*100);
                    $('#state').html('<span class="glyphicon glyphicon-time" style="font-size: 22px; font-weight: normal"></span><span style="font-family: Digi; font-size: 40px;">' + eta + '</span>');
                    $('#target_temp').html(parseInt(x.target));
                    $('#cost').html(x.currency_type + parseFloat(x.cost).toFixed(2));
                  


                }
                else
                {
                    $("#nav_start").show();
                    $("#nav_stop").hide();
                    $('#state').html('<p class="ds-text">'+state+'</p>');
                }

                $('#act_temp').html(parseInt(x.temperature));
                heat_rate = parseInt(x.heat_rate)
                if (heat_rate > 9999) { heat_rate = 9999; }
                if (heat_rate < -9999) { heat_rate = -9999; }
                $('#heat_rate').html(heat_rate);
                if (typeof x.pidstats !== 'undefined') {
                    $('#heat').html('<div class="bar" style="height:'+x.pidstats.out*70+'%;"></div>')
                    }
                if (x.cool > 0.5) { $('#cool').addClass("ds-led-cool-active"); } else { $('#cool').removeClass("ds-led-cool-active"); }
                if (x.air > 0.5) { $('#air').addClass("ds-led-air-active"); } else { $('#air').removeClass("ds-led-air-active"); }
                if (x.temperature > hazardTemp()) { $('#hazard').addClass("ds-led-hazard-active"); } else { $('#hazard').removeClass("ds-led-hazard-active"); }
                if ((x.door == "OPEN") || (x.door == "UNKNOWN")) { $('#door').addClass("ds-led-door-open"); } else { $('#door').removeClass("ds-led-door-open"); }

                state_last = state;

            }
        };

        // Config Socket /////////////////////////////////

        ws_config.onopen = function()
        {
            ws_config.send('GET');
        };

        ws_config.onmessage = function(e)
        {
            console.log (e.data);
            x = JSON.parse(e.data);
            temp_scale = x.temp_scale;
            time_scale_slope = x.time_scale_slope;
            time_scale_profile = x.time_scale_profile;
            kwh_rate = x.kwh_rate;
            currency_type = x.currency_type;

            if (temp_scale == "c") {temp_scale_display = "C";} else {temp_scale_display = "F";}


            $('#act_temp_scale').html('º'+temp_scale_display);
            $('#target_temp_scale').html('º'+temp_scale_display);
            $('#heat_rate_temp_scale').html('º'+temp_scale_display);
            setBuilderUnits();

            switch(time_scale_profile){
                case "s":
                    time_scale_long = "Seconds";
                    break;
                case "m":
                    time_scale_long = "Minutes";
                    break;
                case "h":
                    time_scale_long = "Hours";
                    break;
            }

            if (profiles.length > 0 && selected_profile >= 0 && selected_profile < profiles.length) {
                updateSelectedProfilePreview(profiles[selected_profile], $('#sel_prof_eta').text());
            }

        }

        // Control Socket ////////////////////////////////

        ws_control.onopen = function()
        {

        };

        ws_control.onmessage = function(e)
        {
            //Data from Simulation
            console.log ("control socket has been opened")
            console.log (e.data);
            x = JSON.parse(e.data);
            graph.live.data.push([x.runtime, x.temperature]);
            graph.plot = $.plot("#graph_container", [ graph.profile, graph.live ] , getOptions());

        }

        // Storage Socket ///////////////////////////////

        ws_storage.onopen = function()
        {
            ws_storage.send('GET');
        };


        ws_storage.onmessage = function(e)
        {
            message = JSON.parse(e.data);

            if(message.resp)
            {
                if(message.resp == "FAIL")
                {
                    if (confirm('Overwrite?'))
                    {
                        message.force=true;
                        console.log("Sending: " + JSON.stringify(message));
                        ws_storage.send(JSON.stringify(message));
                    }
                    else
                    {
                        //do nothing
                    }
                }

                return;
            }

            //the message is an array of profiles
            //FIXME: this should be better, maybe a {"profiles": ...} container?
            profiles = message;
            //delete old options in select
            $('#e2').find('option').remove().end();
            // check if current selected value is a valid profile name
            // if not, update with first available profile name
            var valid_profile_names = profiles.map(function(a) {return a.name;});
            if (
              valid_profile_names.length > 0 &&
              $.inArray(selected_profile_name, valid_profile_names) === -1
            ) {
              selected_profile = 0;
              selected_profile_name = valid_profile_names[0];
            }

            // fill select with new options from websocket
            for (var i=0; i<profiles.length; i++)
            {
                var profile = profiles[i];
                //console.log(profile.name);
                $('#e2').append('<option value="'+i+'">'+profile.name+'</option>');

                if (profile.name == selected_profile_name)
                {
                    selected_profile = i;
                    $('#e2').select2('val', i);
                    updateProfile(i);
                }
            }
        };


        $("#e2").select2(
        {
            placeholder: "Select Profile",
            allowClear: true,
            minimumResultsForSearch: -1
        });


        $("#e2").on("change", function(e)
        {
            // Select2 event payload differs between versions; fallback to input value.
            var selected = (e && typeof e.val !== 'undefined') ? e.val : $(this).val();
            updateProfile(selected);
        });

    }
});
