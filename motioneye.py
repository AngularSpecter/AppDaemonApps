import appdaemon.plugins.hass.hassapi as hass

from datetime import datetime
from datetime import timedelta
from enum import Enum

import urllib.request
import json
import re

##################################################
#
# entity   : hass sensor for washing machine power
# 

class MotionEye( hass.Hass ):

  def initialize( self ):

    self.log("Motioneye starting up")
   
## Validate inputs
    self.url_valid = False
    if "URL" in self.args:
      URL = self.args[ "URL" ]
      self.url_valid = True

    self.det_start_scheduler = None

    self.bright_valid   = self.validate_param("brightness_entity", "input_number",  False )
    self.contrast_valid = self.validate_param("contrast_entity"  , "input_number",  False )
    self.hue_valid      = self.validate_param("hue_entity"       , "input_number",  False )
    self.sat_valid      = self.validate_param("saturation_entity", "input_number",  False )
    self.det_valid      = self.validate_param("detection_entity" , "input_boolean", False )
    self.thresh_valid   = self.validate_param("threshold_entity" , "input_number",  False )

    #noise_level
    #text_left
    #locate_motion_mode
    #snapshot
    #snapshot_interval
    #timelapse stuff

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
      #self.listeners.snapshot   = self.listen_event( self.snapshot_CB    , "motion_snapshot"         ) 
      #self.listeners.imag_prop  = self.listen_event( self.camera_props_CB, "motion_cam_prop_changed" )   
      #self.listeners.det_prop   = self.listen_event( self.dete_props_CB  , "motion_det_prop_changed" )
  ###########################################################
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

    with urllib.request.urlopen( full_url ) as response:
      html = response.read().decode('utf-8')
    match = re.findall( '{}</a>\s=\s([\d]+)'.format( prop_name ), html )
    return match[0]

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

