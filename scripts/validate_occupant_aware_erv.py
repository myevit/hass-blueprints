#!/usr/bin/env python3
"""Validate continuous ERV recommendation/controller blueprints."""
from __future__ import annotations

from pathlib import Path
import sys
import yaml
from jinja2 import Environment

ROOT=Path(__file__).resolve().parents[1]
REC=ROOT/'occupant-aware-erv-recommendation.yaml'
CTL=ROOT/'occupant-aware-erv-controller.yaml'

# SafeLoader remains limited to standard YAML types; this constructor only turns
# Home Assistant's scalar !input tag into a plain marker dictionary.
class Loader(yaml.SafeLoader): pass
Loader.add_constructor('!input',lambda loader,node: {'!input':loader.construct_scalar(node)})

def decide(co2,pm,previous_hold=False,pm_valid=True,thresholds_valid=True,hold=55,release=35,override=1200,critical=1400):
    latched=previous_hold if not pm_valid else (pm>=hold or (previous_hold and pm>release))
    if not thresholds_valid or co2 is None:return 'sensor_fault',latched
    if co2>=critical:return 'critical',latched
    if co2>=override:return 'ventilation_required',latched
    if not pm_valid:return 'sensor_fault',latched
    if latched:return 'pollution_hold',latched
    return 'normal_ventilation',latched

def controller_decision(house_mode, blocker_active, switch_state, recommendation, stable=True, switch_age=9999, minimum_on=600, minimum_off=600):
    """Mirror the controller priority order for its safety-critical branches."""
    if blocker_active: return 'hold_manual_blocker'
    if switch_state not in ('on','off'): return 'hold_actuator_unavailable'
    desired='off' if house_mode=='Away' else ('off' if recommendation=='pollution_hold' else 'on')
    if desired==switch_state: return f'no_change_already_{switch_state}'
    if house_mode=='Away': return 'turn_off_away_mode'
    force_on=recommendation not in ('normal_ventilation','pollution_hold')
    if not stable and not force_on: return 'hold_recommendation_persistence'
    if desired=='on' and switch_age<minimum_off and not force_on: return 'hold_minimum_off_time'
    if desired=='off' and switch_age<minimum_on: return 'hold_minimum_on_time'
    return f'turn_{desired}'

def main():
    rec_text=REC.read_text(); ctl_text=CTL.read_text()
    rec=yaml.load(rec_text,Loader=Loader); ctl=yaml.load(ctl_text,Loader=Loader)
    assert rec['blueprint']['domain']=='template'
    assert ctl['blueprint']['domain']=='automation'
    assert 'Version: 2.0.1' in rec['blueprint']['name']
    assert 'Version: 2.1.0' in ctl['blueprint']['name']
    print('PASS: YAML parsed with !input support')

    states={'normal_ventilation','pollution_hold','ventilation_required','critical','sensor_fault'}
    for state in states: assert state in rec_text
    for state in ('normal_ventilation','pollution_hold'): assert state in ctl_text
    forbidden=['clean_air_low_demand','intermittent_window_on','maximum_suppression','intermittent_cycle','intermittent_on_minutes']
    for term in forbidden: assert term not in rec_text+ctl_text,term
    assert "recommendation == 'pollution_hold'" in ctl_text
    assert "house_mode_state == 'Away'" in ctl_text
    assert "force_on: \"{{ house_mode_state != 'Away' and recommendation not in ['normal_ventilation', 'pollution_hold'] }}\"" in ctl_text
    print('PASS: continuous-on policy and no Home Assistant duty cycle')

    cases=[
      ((600,10,False,True,True),'normal_ventilation',False),
      ((600,55,False,True,True),'pollution_hold',True),
      ((600,45,True,True,True),'pollution_hold',True),
      ((600,35,True,True,True),'normal_ventilation',False),
      ((1200,100,True,True,True),'ventilation_required',True),
      ((1400,100,True,True,True),'critical',True),
      ((600,0,False,False,True),'sensor_fault',False),
      ((600,0,True,False,True),'sensor_fault',True),
      ((None,10,False,True,True),'sensor_fault',False),
      ((600,10,False,True,False),'sensor_fault',False),
    ]
    for args,expected_state,expected_latch in cases:
      state,latch=decide(*args)
      assert (state,latch)==(expected_state,expected_latch),(args,state,latch)
    print('PASS: normal-on, PM hysteresis, CO2 override, critical, and fail-on scenarios')
    assert "same_policy" in rec_text
    assert "previous_thresholds.get('pm25_hold_ug_m3', -1)" in rec_text
    print('PASS: threshold changes reset an obsolete pollution latch')

    assert 'default: false' in ctl_text
    assert "live_mode and is_state(manual_blocker, 'off') and control_decision == 'turn_on'" in ctl_text
    assert "live_mode and is_state(manual_blocker, 'off') and control_decision in ['turn_off', 'turn_off_away_mode']" in ctl_text
    assert "blocker_active: \"{{ not is_state(manual_blocker, 'off') }}\"" in ctl_text
    assert ctl['mode']=='restart'
    assert 'hold_manual_blocker' in ctl_text
    print('PASS: dry-run and blocker guard both service actions')

    control_cases=[
      (('Away',False,'on','normal_ventilation',False),'turn_off_away_mode'),
      (('Away',False,'on','critical',False),'turn_off_away_mode'),
      (('Away',True,'on','normal_ventilation',False),'hold_manual_blocker'),
      (('Away',False,'unavailable','normal_ventilation',False),'hold_actuator_unavailable'),
      (('Normal',False,'off','normal_ventilation',False),'hold_recommendation_persistence'),
      (('Normal',False,'off','critical',False),'turn_on'),
    ]
    for args,expected in control_cases:
      assert controller_decision(*args)==expected,(args,controller_decision(*args))
    print('PASS: Away has a single-owner immediate-off priority with explicit manual and actuator holds')

    env=Environment()
    def strings(obj):
      if isinstance(obj,str):
        yield obj
      elif isinstance(obj,dict):
        for value in obj.values(): yield from strings(value)
      elif isinstance(obj,list):
        for value in obj: yield from strings(value)
    for document in (rec,ctl):
      for template in strings(document):
        if '{{' in template or '{%' in template:
          env.parse(template)
    print('PASS: complete embedded Jinja scalar templates parsed')

    household=('sensor.view_plus_carbon_dioxide','sensor.wave_plus_carbon_dioxide','sensor.airgradient_pm2_5','switch.erv')
    for entity in household:
      assert entity not in rec_text and entity not in ctl_text
    print('PASS: household entities remain documentation-only')

if __name__=='__main__':
    try: main()
    except Exception as exc:
      print(f'FAIL: {exc}',file=sys.stderr); raise
