import appdaemon.plugins.hass.hassapi as hass

from datetime import datetime
from datetime import timedelta
from enum import Enum

import urllib.request
import json
import re

##################################################
# MotionEye camera control
#
# An AppDaemon based controller for cameras running the motion daemon.  This class interacts with the
# raw motion daemon over the HTTP interface.  It requires the following settings added to the main motion.conf:
#
#    webcontrol_localhost off
#    webcontrol_html_output on
#    webcontrol_port 7999
#    webcontrol_params 2
#
#
# This enables the external API, sets it to HTML mode and binds it to port 7999.
# As the control is via the motion daemon, this class also works with other packages
# built on motion, such as MotionEye
#
#  Example app config:
#
#  kitchen_camera:
#    module: motioneye
#    class: MotionEye
#    entity_id:         camera.kitchen
#    URL:               "http://192.168.1.10:7999/1/"
#    brightness_entity: input_number.kitchen_camera_brightness
#    contrast_entity:   input_number.kitchen_camera_contrast
#    saturation_entity: input_number.kitchen_camera_saturation
#
# Available App input parameters:
# --------------------------------
#  URL               [ required ] :  Url to the camera.  This should include the API port and the camera instance number.  E.g. http://camera:7999/1/
#  entity_id         [ optional ] :  HASS entity associated with the camera.  This is required to enable binding to events (see below)
#  brightness_entity [ optional ] :  HASS input_number entity to bind to for image brightness value.  Numbers are remapped from motion's 0-255 scale to a 0-100 scale
#  contrast_entity   [ optional ] :  HASS input_number entity to bind to for image contrast value. Numbers are remapped from motion's 0-255 scale to a 0-100 scale
#  hue_entity        [ optional ] :  HASS input_number entity to bind to for image hue value. Numbers are remapped from motion's 0-255 scale to a 0-100 scale
#  saturation_entity [ optional ] :  HASS input_number entity to bind to for image saturation value. Numbers are remapped from motion's 0-255 scale to a 0-100 scale
#  threshold_entity  [ optional ] :  HASS input_number entity to bind to for motion detection threshold value. Numbers is number of pixels
#  detection_entity  [ optional ] :  HASS input_boolean entity to bind to for image contrast value. 
#
#  With valid HASS entities passed through the yaml configuration, the motion daemon's settings will be updated as values in the UI are changed.  This allows for live 
#  updating the values from the UI.  For image related properties( brightness, contrast, hue, saturation ), the values are expected to be in the range of 0:100 from the UI.
#  They are then remapped to the 0:255 range expected by motion.  Updating these values via the HASS entities also causes motion detection to be paused for 2s after the setting
#  update.  This is designed to allow the image to stabilize and not cause a false alarm.
#
#  EVENT calls
#  --------------------------------
#  The motion daemon can also be interacted with via HASS events.  There are three events this daemon binds to and listens for:
#
#  motion_snapshot
#    This event causes the camera to capture (and store locally) a single snapshot frame.
# 
#    event data:
#      entity_id : entity ID of the camera to trigger.  An ID of "ALL" will cause all cameras to trigger
#
#
#  motion_prop_changed
#    This event updates an arbitrary property within the motion daemon.  It is a direct connection to the motion web API.  Property names and values are passed in the event data
#    as key->value pairs.  Values are not rescaled and need to be validated against the motion web API documentation ( https://motion-project.github.io/motion_config.html#Configuration_OptionsAlpha ).
#    For properties that also have a corrisponding registerd hass entity, the hass entity will be updated with the new value.  Any changes made via the event call will be reflected live in the UI
#
#    event data:
#      entity_id     :  entity ID of the camera to update
#      < prop name > : < value >
#       .....
#      < prop name > : < value >
#      
#  motion_det_mode_changed
#    This event enables/disables motion detection at the camera
#
#    event data:
#      entity_id  :  entity ID of the camera to update
#      enabled    : [ True | False ]         
#
############################################################### 

class MotionEye( hass.Hass ):

  def initialize( self ):

    self.log("Motioneye starting up")
   
    ## Validate inputs
    self.url_valid = False
    if "URL" in self.args:
      URL = self.args[ "URL" ]
      self.url_valid = True

    self.entity_registered = False
    if "entity_id" in self.args:
      self.entity_id = self.args[ "entity_id" ]
      self.entity_registered = True
      self.log("Using {} as entity ID for registering event calls".format( self.entity_id ) )

    self.det_start_scheduler = None

    self.bright_valid   = self.validate_param("brightness_entity", "input_number",  False )
    self.contrast_valid = self.validate_param("contrast_entity"  , "input_number",  False )
    self.hue_valid      = self.validate_param("hue_entity"       , "input_number",  False )
    self.sat_valid      = self.validate_param("saturation_entity", "input_number",  False )
    self.det_valid      = self.validate_param("detection_entity" , "input_boolean", False )
    self.thresh_valid   = self.validate_param("threshold_entity" , "input_number",  False )

    should_run = True
    if self.url_valid:
      self.log( "Camera URL set to {}".format( self.args[ "URL" ] ) )
      self.base_url = self.args["URL"]
    else:
      should_run = False

    if self.bright_valid:
      self.log( "Brightness input set to {}".format( self.args[ "brightness_entity" ] ) )

    if self.contrast_valid:
      self.log( "Contrast input set to {}".format( self.args[ "contrast_entity" ] ) )

    if self.hue_valid:
      self.log( "Hue entity set to {}".format( self.args[ "hue_entity" ] ) )

    if self.sat_valid:
      self.log( "Saturation entity set to {}".format( self.args[ "saturation_entity" ] ) )

    if self.det_valid:
      self.log( "Detection entity set to {}".format( self.args[ "detection_entity" ] ) )

    if self.thresh_valid:
      self.log( "Threshold entity set to {}".format( self.args[ "thrshold_entity" ] ) )

    #########################################
    ## Set up callbacks
    if should_run:
      self.log( "Configuration Valid .... initializing" )

      ##Update the UI with the current value
      if self.bright_valid:   self.set_value( self.args["brightness_entity"], self.get_brightness()/255 * 100 )
      if self.contrast_valid: self.set_value( self.args["contrast_entity"  ], self.get_contrast()  /255 * 100 )
      if self.hue_valid:      self.set_value( self.args["hue_entity"       ], self.get_hue()       /255 * 100 )
      if self.sat_valid:      self.set_value( self.args["saturation_entity"], self.get_saturation()/255 * 100 )
      if self.det_valid:      self.set_value( self.args["detection_entity" ], self.get_det_mode()             )
      if self.thresh_valid:   self.set_value( self.args["threshold_entity" ], self.get_threshold()            )

      ##Configure the listeners
      if self.bright_valid:   self.listen_state( self.change_brightness, self.args["brightness_entity"] )
      if self.contrast_valid: self.listen_state( self.change_contrast,   self.args["contrast_entity"  ] )
      if self.hue_valid:      self.listen_state( self.change_hue,        self.args["hue_entity"       ] )
      if self.sat_valid:      self.listen_state( self.change_saturation, self.args["saturation_entity"] )
      if self.det_valid:      self.listen_state( self.change_detection,  self.args["detection_entity" ] )
      if self.thresh_valid:   self.listen_state( self.change_threshold,  self.args["threshold_entity" ] )

      ##Register Event listeners
      self.listeners = {}
      self.listeners["snapshot"   ]                             = self.listen_event( self.snapshot_CB, "motion_snapshot") 
      if self.entity_registered: self.listeners["update_prop"]  = self.listen_event( self.update_setting_event_CB, "motion_prop_changed"    , entity_id = self.entity_id )   
      if self.entity_registered: self.listeners["detection"  ]  = self.listen_event( self.det_mode_CB            , "motion_det_mode_changed", entity_id = self.entity_id )

  ###########################################################
  def snapshot_CB( self, event_name, data, kwargs ):
    #check if we should fire
    if 'entity_id' in data:
      should_fire = False
      if data["entity_id"] == "ALL":                                      should_fire = True
      if self.entity_registered and data["entity_id"] == self.entity_id:  should_fire = True
      if should_fire:
        self.log("Snapshot triggered")
        self.trigger_snapshot()        
  
  #############################################################
  def update_setting_event_CB( self, event_name, data, kwargs ):
    for item in data:
      propName = item
      propVal  = data[item]
      if propName == 'entity_id': continue

      success  = self.set_property( propName, propVal )
      if success:
        if propName == 'brightness' and self.bright_valid:   self.set_value( self.args["brightness_entity"], float(propVal)/255 * 100 )
        if propName == 'contrast'   and self.contrast_valid: self.set_value( self.args["contrast_entity"  ], float(propVal)/255 * 100 )
        if propName == 'hue'        and self.hue_valid:      self.set_value( self.args["hue_entity"       ], float(propVal)/255 * 100 )
        if propName == 'saturation' and self.sat_valid:      self.set_value( self.args["saturation_entity"], float(propVal)/255 * 100 )
        if propName == 'threshold'  and self.thresh_valid:   self.set_value( self.args["threshold_entity" ], float(propVal)           )
      else: self.error("{} is not a valid property".format(propName))
      
  #################################################
  def det_mode_CB( self, event_name, data, kwargs ):
      if 'enabled' in data:
        mode = data['enabled']
        if mode == 'True' or mode == 'true' or mode == 'On' or mode == 'on' or mode == '1': 
          self.start_detection()
          if self.det_valid: self.set_value( self.args["detection_entity"], "On" )
    
        if mode == 'False' or mode == 'false' or mode == 'Off' or mode == 'off' or mode == '0': 
          self.stop_detection()
          if self.det_valid: self.set_value( self.args["detection_entity"], "Off" )

  ###################################################################
  def state_change( self, entity, attribute, old, new, kwargs ):
    self.log( entity )
    self.log( attribute )
    self.log( "{} -> {}".format( old, new ) )
  
  def change_brightness( self, entity, attribute, old, new, kwargs ):
    det_mode = self.get_det_mode()
    self.pause_detection()
    new_val = self.set_brightness( float(new)/100*255 )
    if det_mode: self.schedule_det_start()
    self.log( "Brightness updated to {} [ {} ]".format( new, new_val ) )

  def change_contrast( self, entity, attribute, old, new, kwargs ):
    det_mode = self.get_det_mode()
    self.pause_detection()
    new_val = self.set_contrast( float(new)/100*255 )
    if det_mode: self.schedule_det_start()
    self.log( "Contrast updated to {} [ {} ]".format( new, new_val ) )

  def change_hue( self, entity, attribute, old, new, kwargs ):
    det_mode = self.get_det_mode()
    self.pause_detection()
    new_val = self.set_hue( float(new)/100*255 )
    if det_mode: self.schedule_det_start()
    self.log( "Hue updated to {} [ {} ]".format( new, new_val ) )

  def change_saturation( self, entity, attribute, old, new, kwargs ):
    det_mode = self.get_det_mode()
    self.pause_detection()
    new_val = self.set_saturation( float(new)/100*255 )
    if det_mode: self.schedule_det_start()
    self.log( "Saturation updated to {} [ {} ]".format( new, new_val ) )

  def change_threshold( self, entity, attribute, old, new, kwargs ):
    new_val = self.set_threshold( new )
    self.log( "Threshold set to {}".format( new ) )

  def change_detection( self, entity, attribute, old, new, kwargs ):
    if new == "On" : 
      self.start_detection()
    else:
      self.pause_detection()
    self.log( "Detection updated to {}".format( new ) )

  ##################################################################
  def get_property( self, prop_name ):
    url_stub = 'config/get?query={}'.format( prop_name )
    full_url = '{}{}'.format(self.base_url, url_stub )

    with urllib.request.urlopen( full_url ) as response:
      html = response.read().decode('utf-8')

    match = re.findall( '{}\s=\s([\d]+)'.format( prop_name ), html )
    return match[0]
  
  def set_property( self, prop_name, value ):
    self.log( "Setting {} to {}".format( prop_name, value ) )
    url_stub = 'config/set?{}={}'.format( prop_name, value )
    full_url = '{}{}'.format(self.base_url, url_stub )

    try:
      with urllib.request.urlopen( full_url ) as response:
        html = response.read().decode('utf-8')
    except:
      self.log( "ERROR" )
      return False

    return True

 #####################################
  def trigger_snapshot( self ):
    url_stub = 'action/snapshot'
    full_url = '{}{}'.format(self.base_url, url_stub )

    with urllib.request.urlopen( full_url ) as response:
      html = response.read().decode('utf-8') 
 
 #####################################
  def get_det_mode( self ):
    url_stub = 'detection/status'
    full_url = '{}{}'.format(self.base_url, url_stub )

    with urllib.request.urlopen( full_url ) as response:
      html = response.read().decode('utf-8')

    match = re.findall( 'Detection\sstatus\s([\w]+)', html )
    return match[0] == 'ACTIVE'

  ###############################
  def set_det_mode( self, mode ):
    if mode:
      url_stub = 'detection/start'
    else:
      url_stub = 'detection/pause'

    full_url = '{}{}'.format(self.base_url, url_stub )

    with urllib.request.urlopen( full_url ) as response:
      html = response.read().decode('utf-8')

  ################################
  def pause_detection( self, kwargs = {} ):
    self.set_det_mode( False )

  def start_detection( self, kwargs = {} ):
    self.set_det_mode( True )

  def schedule_det_start( self ):
    if self.det_start_scheduler:
      self.log("Killing old scheduler")
      self.cancel_timer( self.det_start_scheduler )
    self.log("Scheduling detection enabled in 2s")
    self.det_start_scheduler = self.run_in( self.start_detection, 2 )


 ######################################
  def set_brightness( self, value ):
    self.set_property( 'brightness', value )

  def get_brightness( self ):
    return float( self.get_property( 'brightness' ) )

 ######################################
  def set_contrast(self, value ):
    self.set_property( 'contrast', value )

  def get_contrast( self ):
    return float( self.get_property( 'contrast' ) )

 ######################################
  def set_saturation( self, value ):
    self.set_property( 'saturation', value )
 
  def get_saturation( self ):
    return float( self.get_property( 'saturation' ) )

 ######################################
  def set_hue( self, value ):
    self.set_property( 'saturation', value )

  def get_hue( self ):
    return float( self.get_property( 'saturation' ) )

 ######################################
  def set_threshold( self, value ):
    self.set_property( 'threshold', value )

  def get_threshold( self ):
    return int( self.get_property( 'threshold' ) )

#######################################
  def terminate( self ):
    pass

 
  #########################################################
  def validate_param( self, param, param_type = "" , required = False ):

    err_level = "CRITICAL" if required else "WARNING"

    if param not in self.args:
      self.error("{} was not found in config".format( param ), level=err_level)
      return False
   
    val = self.args[param]
    
    if type( val ) is str:
      if not self.entity_exists( val ):
        self.error("{} is an invalid entity for {}".format( self.args[param], param ), level=err_level )
        return False
      if param_type not in self.args[param]:
        self.error("{} is not a {} and cannot be used".format( self.args[param]. param_type ), level=err_level )
        return False
      return True 

    if type( val ) is list:
      valid_props = {}

      for entity in val:
        #Check if the entity exists
        valid_props[ entity ] = self.entity_exists(entity)
        if not valid_props[ entity ] : self.error( "{} entity does not exist".format( entity ), level=err_level )

        #Compare the name against the param_type
        if valid_props[ entity ] and param_type != "" :
          if param_type not in entity:
            self.error("{} is not a {} and cannot be used".format( entity, param_type ), level="WARNING" )
            valid_props[ entity ] = False
             
      return valid_props

    return False

