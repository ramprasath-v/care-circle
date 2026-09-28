const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const microphone = process.env.CARE_MIC_TEST === '1';

class Element {
  constructor() { this.children = []; this._text = ''; this.disabled = false; this.classList = {add() {}, remove() {}}; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  prepend(child) { this.children.unshift(child); }
  replaceChildren(...children) { this.children = children; this._text = ''; }
  setAttribute() {}
}
const elements = new Map();
const element = selector => {
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
};
const timers = [];
const calls = [];
const spoken = [];
const diagnostics = [];
let progressSettling = false;
let simulatedTranscript = '';
const incident = 'voice-ui-incident';
const state = {
  incident_id: incident, status: 'OPEN', resolution_state: 'OPEN', assigned_caregiver: 'john',
  medication_status: 'unresolved', home_smart_plug: 'on', care_task_status: 'OPEN',
  completed_actions: [], pending_actions: [], draft_actions: [], next_check_at: null,
  next_appointment: {name: 'Cardiology', time: '14:30'},
};
let nextJob = 0;
const jobs = new Map();
const result = value => ({ok: true, json: async () => value});
const context = vm.createContext({
  document: {querySelector: element, querySelectorAll: () => [], createElement: () => new Element()},
  fetch: async (url, options) => {
    if (url === '/api/transcribe') {
      assert.equal(options.method, 'POST');
      assert.equal(options.headers['Content-Type'], 'application/octet-stream');
      assert.ok(options.body.size >= 6400);
      assert.equal(element('#mic').disabled, true);
      await vm.runInContext('startRecording()', context);
      assert.equal(vm.runInContext('recording', context), false, 'a second recording cannot overlap transcription');
      if (process.env.CARE_TRANSCRIBE_URL) return fetch(process.env.CARE_TRANSCRIBE_URL, options);
      return result({transcript: simulatedTranscript, provider: 'simulated-transcribe', latency_ms: 1, sample_rate_hz: 16000});
    }
    const body = JSON.parse(options.body);
    if (url === '/api/speak') {
      assert.equal(progressSettling, false, 'speech must wait for the SSE completion barrier');
      assert.equal(vm.runInContext('busy', context), false, 'speech must start after working=false');
      assert.equal(element('#working-label-text').textContent, 'CareCircle is ready');
      assert.equal(element('#working-spinner').hidden, true, 'speech must start after the spinner stops');
      spoken.push(body.text);
      return {ok: true, blob: async () => Buffer.from('audio')};
    }
    if (url === '/api/voice-intent') {
      const phrase = body.transcript.toLowerCase().replace(/[.!?,]+$/, '').trim();
      const n = body.pending_count;
      const decision = n > 1 && ['approve all', 'yes to all', 'approve them all', 'go ahead with all'].includes(phrase) ? 'APPROVE_ALL'
        : n > 1 && ['reject all', 'cancel all', 'no to all'].includes(phrase) ? 'REJECT_ALL'
        : n === 1 && ['yes', 'approve', 'approve it', 'go ahead', 'do it'].includes(phrase) ? 'APPROVE'
        : n === 1 && ['no', 'reject', 'cancel', "don't do it"].includes(phrase) ? 'REJECT'
        : n > 1 && ['yes', 'no'].includes(phrase) ? 'AMBIGUOUS' : 'NONE';
      return result({decision});
    }
    if (url === '/api/jobs') {
      const jobId = String(++nextJob);
      jobs.set(jobId, body);
      calls.push(body.operation);
      return result({job_id: jobId, session_id: body.arguments.session_id || 'voice-browser-demo'});
    }
    throw new Error(`Unexpected fetch ${url}`);
  },
  EventSource: class {
    constructor(url) {
      const {operation, arguments: args} = jobs.get(url.split('/')[3]);
      queueMicrotask(() => {
        const send = item => this.onmessage({data: JSON.stringify(item)});
        let value;
        if (operation === 'get_household_briefing') value = {
          medication_status: {unresolved: ['morning']}, home_status: {entry: {summary: 'No walk'}, smoke_co: {status: {smoke: 'normal', co: 'normal'}}, stove: {status: {smart_plug: state.home_smart_plug}}},
          next_appointment: state.next_appointment, open_care_tasks: [{}], routine_deviations: [{routine_id: 'walk', status: 'not_observed'}],
          care_team: [{name: 'Maya', role: 'primary caregiver', on_call: false}, {name: 'John', role: 'backup caregiver', on_call: true}],
        };
        else if (operation === 'get_incident_status') value = structuredClone(state);
        else if (operation === 'coordinate_care_request') {
          const utterance = args.utterance.toLowerCase();
          let proposed_actions = [];
          let tool = 'create_incident';
          let summary = 'Care request handled';
          let evidence = [];
          let awaiting_safety_answers = false;
          if (utterance.includes('plug')) {
            tool = 'request_device_action';
            state.pending_actions = [{action_id: 'device', type: 'device_change', description: 'Turn off simulated plug', approval_required: true, approval_state: 'PENDING'}];
            proposed_actions = state.pending_actions;
          } else if (utterance.includes('rest of')) {
            tool = 'prepare_ride_request';
            state.draft_actions = ['refill_draft', 'ride_draft', 'supply_draft'].map(type => ({action_id: type, type, description: type, approval_required: true, approval_state: 'PENDING', execution_state: 'DRAFT'}));
            state.pending_actions = state.draft_actions;
            summary = 'Prepared drafts for a medication refill, the 2:30 PM cardiology ride, and a weekly pill organizer. Nothing was purchased, booked, or sent to a pharmacy.';
          } else if (utterance.includes('john checked')) {
            tool = 'record_dose_status';
            state.medication_status = 'taken'; state.care_task_status = 'COMPLETED'; state.resolution_state = 'RESOLVED'; state.status = 'RESOLVED';
            for (const action of state.pending_actions)
              if (action.action_id === 'follow-up-escalation') {
                action.approval_state = 'REJECTED';
                action.provider_result = {status: 'superseded', reason: 'incident_resolved'};
              }
            state.pending_actions = state.pending_actions.filter(action => action.approval_state === 'PENDING');
            evidence = [{source: 'caregiver_report', description: 'John reported that Dad confirmed taking the morning medication.'}];
          } else if (utterance.includes('awake and responsive')) {
            tool = 'collect_safety_answers';
            state.assigned_caregiver = 'john'; state.care_task_status = 'ASSIGNED';
            state.pending_actions = [{action_id: 'caregiver', type: 'notify_primary_caregiver', description: 'Alert John', approval_required: true, approval_state: 'PENDING'}];
            proposed_actions = state.pending_actions;
          } else if (utterance.includes('confused')) {
            tool = 'collect_safety_answers';
            summary = 'Is Dad awake and responsive? Does he have chest pain, difficulty breathing, or trouble speaking?';
            awaiting_safety_answers = true;
          } else {
            state.pending_actions = [{action_id: 'caregiver', type: 'notify_primary_caregiver', description: 'Alert John', approval_required: true, approval_state: 'PENDING'}];
            proposed_actions = state.pending_actions;
          }
          send({type: 'progress', kind: 'tool', operation: tool, status: 'COMPLETE', component: 'Care Coordinator Agent'});
          value = {incident_id: incident, summary, risk_level: awaiting_safety_answers ? 'low' : 'high', proposed_actions, evidence, awaiting_safety_answers};
        } else if (operation === 'confirm_action') {
          const action = state.pending_actions.find(item => item.action_id === args.action_id);
          assert.ok(action, 'A refresh must not repeat a mutation');
          state.pending_actions = state.pending_actions.filter(item => item !== action);
          if (action.type.endsWith('_draft')) {
            action.approval_state = args.approved ? 'APPROVED' : 'REJECTED';
            value = {incident_id: incident, execution_state: 'DRAFT', approval_state: action.approval_state};
          } else {
            state.completed_actions.push({...action, execution_state: 'COMPLETED'});
            if (args.action_id === 'device') {
              state.home_smart_plug = 'off';
              state.pending_actions.push({
                action_id: 'stale-caregiver', type: 'caregiver_alert',
                description: 'Ask backup caregiver John to review the unresolved incident.',
                approval_required: true, approval_state: 'PENDING', execution_state: 'COMPLETED',
              });
            }
            else state.next_check_at = new Date(Date.now() + 60000).toISOString();
            send({type: 'progress', kind: 'tool', operation: args.action_id === 'device' ? 'request_device_action' : 'send_approved_alert', status: 'COMPLETE', component: 'Care Coordinator Agent'});
            value = {incident_id: incident, execution_state: 'COMPLETED', next_check_at: state.next_check_at};
          }
        } else throw new Error(`Unexpected MCP call ${operation}`);
        progressSettling = true;
        send({type: 'result', value});
        queueMicrotask(() => {
          send({type: 'progress', kind: 'agent', operation: 'settled-progress', status: 'COMPLETE', component: 'Care Coordinator Agent'});
          progressSettling = false;
          send({type: 'done'});
        });
      });
    }
    close() {}
  },
  setTimeout: (fn, delay) => {const timer = {fn, delay}; timers.push(timer); return timer;},
  clearTimeout: timer => {const index = timers.indexOf(timer); if (index >= 0) timers.splice(index, 1);},
  Audio: class {play() {return Promise.resolve()} pause() {}},
  URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}},
  Date, Math, JSON, Set, Object, String,
  Blob,
  console: {info: (...args) => diagnostics.push(args)},
});
const script = fs.readFileSync(path.join(__dirname, '../src/carecircle/web_assets/app.js'), 'utf8');
vm.runInContext(script, context);
const dispatch = async text => {
  if (microphone) {
    simulatedTranscript = text;
    vm.runInContext(`recorder={chunks:[new Uint8Array(7000)],processor:{disconnect(){}},source:{disconnect(){}}};mediaStream={getTracks:()=>[]};audioContext={close:async()=>{}};recording=true`, context);
    await vm.runInContext('stopRecording()', context);
    assert.equal(element('#mic').disabled, false);
  } else {
    element('#prompt').value = text;
    await element('#prompt-form').onsubmit({preventDefault() {}});
  }
};
const shown = selector => element(selector).textContent;

async function main() {
  if (process.env.CARE_MIC_ONLY === '1') {
    const concern = "Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.";
    const safety = 'He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.';
    await dispatch(concern);
    assert.equal(vm.runInContext('conversation.mode', context), 'AWAITING_SAFETY_ANSWERS');
    const id = vm.runInContext('conversation.incident_id', context);
    await dispatch(safety);
    assert.equal(vm.runInContext('conversation.incident_id', context), id);
    assert.equal(vm.runInContext('conversation.awaiting_safety_answers', context), false);
    assert.equal(vm.runInContext('conversation.mode', context), 'AWAITING_SINGLE_APPROVAL');
    await dispatch('Yes.');
    assert.equal(vm.runInContext('conversation.incident_id', context), id);
    assert.equal(vm.runInContext('conversation.mode', context), 'COMPLETE');
    assert.equal(state.home_smart_plug, 'on');
    assert.equal(calls.filter(name => name === 'coordinate_care_request').length, 2);
    assert.equal(calls.filter(name => name === 'confirm_action').length, 1);
    assert.ok([...jobs.values()].every(job => !job.arguments.session_id || job.arguments.session_id === 'voice-browser-demo'));
    const turns = diagnostics.filter(([name]) => name === 'carecircle_turn');
    assert.equal(turns.length, 3);
    assert.deepEqual(turns.map(([,entry]) => JSON.parse(entry).selected_intent), ['NEW_CONCERN','SAFETY_ANSWER','APPROVE']);
    return;
  }
  const briefingPhrases = [
    'CareCircle, how is Dad doing this morning?', 'How is Dad doing?',
    'How is Dad doing today?', "How's Dad?", "Give me Dad's morning briefing.",
    "What's going on with Dad today?", 'Can you give me an update on Dad?',
  ];
  for (const phrase of briefingPhrases) {
    const before = calls.length;
    await dispatch(phrase);
    assert.deepEqual(calls.slice(before), ['get_household_briefing'], `${phrase} must use only the briefing read`);
    assert.doesNotMatch(shown('#summary') + spoken.at(-1), /awake and responsive|Risk: low/i);
  }
  assert.equal(vm.runInContext('conversation.incident_id', context), null);
  assert.equal(vm.runInContext('observedTools.has("create_incident") || observedTools.has("collect_safety_answers") || observedTools.has("evaluate_red_flag_rules")', context), false);
  assert.equal(vm.runInContext('classifyCareIntent("How is Dad doing this morning? He seems confused.")', context), 'NEW_CONCERN');
  for (const phrase of ['Dad seems confused.', 'Dad says he may have missed his medication.', 'Dad has chest pain.', "Dad hasn't checked in and something seems wrong.", 'Dad fell.', 'Dad is having trouble breathing.']) {
    assert.equal(vm.runInContext(`classifyCareIntent(${JSON.stringify(phrase)})`, context), 'NEW_CONCERN');
  }
  assert.equal(vm.runInContext('classifyCareIntent("Dad status today?")', context), 'BRIEFING');
  assert.equal(vm.runInContext('classifyCareIntent("What is the status of Dad’s incident?")', context), 'INCIDENT_STATUS');
  assert.match(shown('#summary-grid'), /Kitchen plug: on/);
  assert.match(shown('#summary'), /Next appointment: Cardiology at 14:30/);
  assert.match(spoken.at(-1), /morning medication hasn't been confirmed/);
  assert.match(spoken.at(-1), /morning walk hasn't been observed/);
  assert.match(spoken.at(-1), /no smoke or carbon-monoxide alerts.*kitchen smart plug is still on/);
  assert.match(spoken.at(-1), /Maya is unavailable.*John is available/);
  assert.match(spoken.at(-1), /cardiology appointment is at 2:30 PM/);
  assert.doesNotMatch(spoken.at(-1), /14:30|Morning medication:|MCP|SNS|EventBridge|ActionLedger/);
  assert.ok((spoken.at(-1).match(/\./g) || []).length >= 3 && (spoken.at(-1).match(/\./g) || []).length <= 5);
  assert.equal(calls.filter(name => name === 'coordinate_care_request').length, 0);
  await dispatch("Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.");
  assert.equal(calls.at(-1), 'get_incident_status');
  assert.match(shown('#summary-grid'), /Caregiver task: OPEN/);
  assert.equal(vm.runInContext('conversation.mode', context), 'AWAITING_SAFETY_ANSWERS');
  assert.equal(vm.runInContext('classifyCareIntent("He is awake and responsive. No chest pain or breathing trouble.")', context), 'SAFETY_ANSWER');
  assert.doesNotMatch(shown('#summary') + spoken.at(-1), /Risk: low/i);
  assert.match(spoken.at(-1), /awake and responsive/i);
  const originalIncident = vm.runInContext('conversation.incident_id', context);
  const beforeApprovalPhrase = calls.length;
  await dispatch('Approve all.');
  assert.equal(calls.length, beforeApprovalPhrase, 'approval without pending actions must not reach triage');
  await dispatch('He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.');
  assert.match(spoken.at(-1), /Would you like me to do that\?$/);
  assert.match(spoken.at(-1), /caregiver check/);
  assert.equal(vm.runInContext('conversation.mode', context), 'AWAITING_SINGLE_APPROVAL');
  assert.equal(vm.runInContext('conversation.awaiting_safety_answers', context), false);
  assert.equal(vm.runInContext('conversation.safety_question', context), null);
  assert.equal(vm.runInContext('conversation.session_id', context), 'voice-browser-demo');
  assert.ok([...jobs.values()].every(job => job.arguments.session_id === undefined || job.arguments.session_id === 'voice-browser-demo'));
  assert.equal(vm.runInContext('conversation.incident_id', context), originalIncident);
  assert.equal(vm.runInContext('conversation.session_id', context), 'voice-browser-demo');
  context.oldSnapshot = {...structuredClone(state), incident_id: 'previous-voice-incident', medication_status: 'taken', home_smart_plug: 'off'};
  vm.runInContext('renderIncidentState(oldSnapshot)', context);
  assert.match(shown('#summary-grid'), /Medication: unresolved/);
  assert.match(shown('#summary-grid'), /Kitchen plug: on/);
  await dispatch('Yes.');
  assert.match(shown('#summary'), /Caregiver alert sent/);
  assert.doesNotMatch(shown('#summary'), /medication|plug/i);
  assert.match(shown('#state-cards'), /Alert John — Completed/);
  assert.match(shown('#state-cards'), /Follow-up — Scheduled/);
  assert.equal(spoken.at(-1), "I've sent the caregiver alert. A follow-up is scheduled.");
  assert.equal(state.medication_status, 'unresolved');
  assert.equal(state.home_smart_plug, 'on');
  assert.equal(vm.runInContext('conversation.mode', context), 'COMPLETE');
  assert.equal(calls.at(-1), 'get_incident_status');
  await dispatch("Also help with the rest of Dad's day.");
  assert.match(shown('#actions'), /3 prepared actions.*Medication refill request.*Ride request.*Pill-organizer request.*Approve All.*Review Individually.*Reject All/i);
  assert.equal(vm.runInContext('conversation.mode', context), 'AWAITING_MULTI_APPROVAL');
  assert.equal(vm.runInContext('conversation.pending_actions.length', context), 3);
  assert.match(spoken.at(-1), /approve all of them\?$/);
  assert.equal(state.home_smart_plug, 'on');
  const coordinated = calls.filter(name => name === 'coordinate_care_request').length;
  const approvalsBefore = calls.filter(name => name === 'confirm_action').length;
  vm.runInContext('conversation.awaiting_safety_answers = true; conversation.safety_question = "stale question"', context);
  await dispatch('Approve all.');
  assert.equal(calls.filter(name => name === 'coordinate_care_request').length, coordinated, 'approve all must not reach triage');
  assert.equal(calls.filter(name => name === 'confirm_action').length, approvalsBefore + 3);
  assert.deepEqual(state.draft_actions.map(item => item.approval_state), ['APPROVED', 'APPROVED', 'APPROVED']);
  assert.equal(state.medication_status, 'unresolved');
  assert.equal(state.home_smart_plug, 'on');
  assert.match(spoken.at(-1), /Nothing has been ordered or booked/);
  assert.equal(vm.runInContext('conversation.incident_id', context), originalIncident);
  assert.equal(vm.runInContext('conversation.pending_actions.length', context), 0);
  assert.equal(vm.runInContext('conversation.awaiting_safety_answers', context), false);
  assert.equal(vm.runInContext('conversation.safety_question', context), null);
  assert.equal(vm.runInContext('conversation.mode', context), 'COMPLETE');
  assert.doesNotMatch(shown('#summary') + spoken.at(-1), /awake and responsive|stale question/i);
  assert.match(shown('#state-cards'), /ride request — DRAFT/);
  assert.match(shown('#state-cards'), /refill request — DRAFT/);
  assert.match(shown('#state-cards'), /supply request — DRAFT/);
  await dispatch("Turn off Dad's kitchen smart plug.");
  assert.doesNotMatch(shown('#summary') + spoken.at(-1), /awake and responsive|stale question/i);
  assert.equal(vm.runInContext('conversation.incident_id', context), originalIncident);
  assert.match(shown('#summary-grid'), /Kitchen plug: on/);
  assert.equal(spoken.at(-1), "Turning off Dad's kitchen smart plug requires confirmation. Should I proceed?");
  assert.equal(state.home_smart_plug, 'on', 'device proposal alone cannot execute');
  const speechBeforeDeviceConfirmation = spoken.length;
  await dispatch('Yes.');
  assert.match(shown('#summary'), /Simulated kitchen plug turned off/);
  assert.doesNotMatch(shown('#summary'), /medication/i);
  assert.match(shown('#summary-grid'), /Kitchen plug: off/);
  assert.match(shown('#state-cards'), /Turn off simulated plug — Completed/);
  assert.match(shown('#state-cards'), /Alert John — Completed/);
  assert.match(shown('#state-cards'), /ride request — DRAFT/);
  assert.equal(shown('#actions'), '');
  assert.equal(vm.runInContext('conversation.pending_actions.length', context), 0);
  assert.equal(vm.runInContext('lastPromptedAction', context), null);
  assert.equal(spoken.at(-1), "Done. Dad's kitchen smart plug is now off.");
  assert.deepEqual(spoken.slice(speechBeforeDeviceConfirmation), ["Done. Dad's kitchen smart plug is now off."]);
  assert.doesNotMatch(spoken.at(-1), /care concern|caregiver check/i);
  assert.equal(state.medication_status, 'unresolved');
  state.pending_actions = [{
    action_id: 'follow-up-escalation', type: 'caregiver_alert',
    description: 'Ask backup caregiver John to review the unresolved incident.',
    approval_required: true, approval_state: 'PENDING', execution_state: 'PENDING',
  }];
  context.followUpSnapshot = structuredClone(state);
  vm.runInContext('renderIncidentState(followUpSnapshot)', context);
  assert.match(shown('#actions'), /Ask backup caregiver John to review the unresolved incident/);
  await dispatch('John checked on Dad. Dad is okay and confirmed he already took his morning medication.');
  assert.match(shown('#summary-grid'), /Medication: taken/);
  assert.match(shown('#summary-grid'), /Caregiver task: COMPLETED/);
  assert.match(shown('#state-cards'), /Incident — Resolved/);
  assert.equal(shown('#actions'), '');
  assert.equal(vm.runInContext('conversation.pending_actions.length', context), 0);
  assert.equal(vm.runInContext('lastPromptedAction', context), null);
  assert.match(spoken.at(-1), /caregiver task is complete/);
  assert.equal(state.home_smart_plug, 'off');
  await dispatch("What's the status of Dad's incident?");
  assert.match(shown('#summary'), /Incident RESOLVED.*Caregiver task: COMPLETED.*Prepared drafts: refill, ride, supply.*Next appointment: Cardiology at 14:30/);
  assert.match(spoken.at(-1), /Dad's incident is resolved/);
  assert.match(spoken.at(-1), /2:30 PM/);
  assert.doesNotMatch(spoken.at(-1), /RESOLVED|COMPLETED|OPEN|FOLLOW_UP_DUE|Prepared drafts:|Caregiver:|14:30|MCP|SNS|EventBridge|ActionLedger/);
  assert.doesNotMatch(vm.runInContext('voiceStatus({...oldSnapshot, draft_actions:[], next_check_at:null})', context), /draft|follow-up/i);
  assert.equal(calls.filter(name => name === 'confirm_action').length, 5);
  assert.equal(calls.filter(name => name === 'get_incident_status').length, 12);
  assert.equal(calls.filter(name => name === 'get_household_briefing').length, briefingPhrases.length);

  // A separate open incident's one-shot due-time notification refreshes the authoritative status once.
  state.resolution_state = 'OPEN'; state.status = 'OPEN';
  await vm.runInContext('refreshIncident(incidentId)', context);
  const collisionTimer = timers.at(-1);
  const beforeCollision = calls.length;
  const speechBeforeCollision = spoken.length;
  vm.runInContext('foregroundWork = 1', context);
  await collisionTimer.fn();
  assert.equal(calls.length, beforeCollision, 'background refresh must not start competing MCP work');
  assert.ok(vm.runInContext('deferredFollowUpRefresh !== null', context));
  assert.doesNotMatch(shown('#error'), /already working/i);
  assert.equal(spoken.length, speechBeforeCollision);
  state.status = 'FOLLOW_UP_DUE'; state.next_check_at = null;
  context.dueSnapshot = structuredClone(state);
  vm.runInContext('renderIncidentState(dueSnapshot); endForegroundWork()', context);
  assert.equal(vm.runInContext('deferredFollowUpRefresh', context), null, 'authoritative foreground state must coalesce the deferred read');
  assert.equal(calls.length, beforeCollision);

  state.resolution_state = 'OPEN'; state.status = 'OPEN';
  state.next_check_at = new Date(Date.now() + 60000).toISOString();
  await vm.runInContext('refreshIncident(incidentId)', context);
  const timer = timers.at(-1);
  assert.ok(timer && timer.delay > 0);
  const before = calls.length;
  await timer.fn();
  assert.equal(calls.length, before + 1);
  const retry = timers.at(-1);
  assert.ok(retry && retry !== timer && retry.delay === 10000);
  state.status = 'FOLLOW_UP_DUE';
  state.next_check_at = null;
  await retry.fn();
  assert.equal(calls.length, before + 2);
  assert.equal(calls.at(-1), 'get_incident_status');
  assert.match(shown('#state-cards'), /Follow-up — Due/);
  assert.match(spoken.at(-1), /follow-up is due/);
  assert.doesNotMatch(spoken.at(-1), /FOLLOW_UP_DUE|Follow-up:/);
  assert.equal(calls.filter(name => name === 'confirm_action').length, 5);
  assert.ok(spoken.every(text => !/MCP|SNS|EventBridge|ActionLedger|\b(?:OPEN|COMPLETED|FOLLOW_UP_DUE)\b/.test(text)));
  const turnDiagnostics = diagnostics.filter(([name]) => name === 'carecircle_turn');
  const timingDiagnostics = diagnostics.filter(([name]) => name === 'carecircle_timing');
  assert.ok(turnDiagnostics.length >= 3);
  assert.ok(turnDiagnostics.every(([, value]) => JSON.parse(value).source === (microphone ? 'microphone' : 'typed')));
  assert.ok(timingDiagnostics.length >= 3);
  assert.ok(timingDiagnostics.some(([, value]) => JSON.parse(value).jobs.length >= 1));
  assert.ok(timingDiagnostics.every(([, value]) => JSON.parse(value).total_to_audio_start_ms >= 0));
  assert.ok(diagnostics.every(([, value]) => !value.includes('Dad just called') && !value.includes('awake and responsive')));
}
main().catch(error => {console.error(error); process.exitCode = 1});
