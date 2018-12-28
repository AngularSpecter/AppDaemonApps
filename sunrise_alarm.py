import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime
from datetime import timedelta
from enum import Enum

##################################################
#
# time_entity   : hass input_datetime for alarm time
# lights        : map of hass light entities to control
# pre_trip      : hass input_number for minutes before alarm to start lights [ default = 30 ]
# enabled_entity: hass input_boolean to control alarm enable/disable ( optional )
# weekend_entity: hass input_boolean to enable/disable alarm on weekends ( optional )
# 

class dim_mode( Enum ):
  level = 0             # bring all lights in the room up to match the brightest
  scale = 1             # leave all lights as they are and scale independantly


class SunriseAlarm( hass.Hass ):

  def initialize( self ):
    self.log("Sunrise Alarm starting up")
 
    self.time_valid   = self.validate_param( "time_entity", "input_datetime", True )
    self.lights_valid = self.validate_param( "lights", "light", True )
    self.mode         = dim_mode.scale
 
    if self.time_valid and ( any( self.lights_valid.values() ) ):

      self.alarm_h          = False
      self.should_interrupt = False

      ###################################################
      self.active_lights = []
      for light_id in self.lights_valid:
        if self.lights_valid[light_id]:
          self.active_lights.append( light_id )

 
      ####################################################
      if self.validate_param( "pre_trip", "input_number"):
        self.pre_trip = datetime.timedelta( minutes = self.get_state( self.args[ "pre_trip" ] ) )
        self.log( "Alarm starting up with {} minutes of pre-trip".format( self.pre_trip ) )
        self.listen_state( self.new_pretrip, self.args[ "pre_trip" ] )
      else:
        self.pre_trip = timedelta( minutes = 30 )
        self.log( "Alarm starting up with default {} minutes of pre-trip".format( self.pre_trip ))

      ####################################################
      if self.validate_param("enabled_entity", "input_boolean" ):
        self.alarm_enabled = self.get_state( self.args["enabled_entity"] ) == "on"
        self.log( "Alarm staring up with alarm in {} state".format( self.alarm_enabled ) )

        self.listen_state( self.new_enable, self.args["enabled_entity"] )
      else:
        self.alarm_enabled = True
        self.error("enable_entity not provided.  Alarm will not be controllable", level="WARNING")

      ####################################################
      if self.validate_param("weekend_entity", "input_boolean"):
        self.weekends_enabled = self.get_state( self.args["weekend_entity"] ) == "on"
        self.log( "Alarm staring up with weekends in {} state".format( self.weekends_enabled ) )

        self.listen_state( self.new_wknd, self.args["weekend_entity"] )
      else:
        self.weekends_enabled = True
        self.error("weekend_entity not provided.  Alarm will function everyday", level="WARNING")

      ### Configure the alarm callback
      alarm_time_entity    = self.args["time_entity"]
      self.listen_state( self.new_time, self.args["time_entity"] )
      self.alarm_time = datetime.strptime( self.get_state( self.args["time_entity"] ), '%H:%M:%S' )
      self.log("Alarm starting up set to {}".format( self.alarm_time.time()  ) )

      if self.alarm_enabled:
        self.set_alarm( )

    ### Debug
   # self.sequence_lights( None )

 #######################################
  def terminate( self ):
    pass

  ###########################################################
  def new_time( self, entity, attribute, old, new, kwargs ):
    self.log( "Time changed to {}".format( new ) )
    self.kill_alarm()
    self.alarm_time   = datetime.strptime( new, '%H:%M:%S' )
    if self.alarm_enabled: self.set_alarm()
  
  ###########################################################
  def new_pretrip( self, entity, attribute, old, new, kwargs ):

    if new < 10:   #10 minute minimum fade in time
      self.log( "Pre-trip time less than 10 minute minimum...defaulting", level="WARNING" )
      new = 10
      self.set_state( entity, new )

    self.log( "Pre-trip time changed to {}".format( new ) )
    self.kill_alarm()
    self.pre_trip = timedelta( minutes = self.get_state( new ) )
    if self.alarm_enabled: set_alarm()


  #########################################################
  def new_enable( self, entity, attributes, old, new, kwargs ):
    self.log( "Alarm enable switched to {}".format( new ) )
    self.alarm_enabled = new == "on"

    if self.alarm_enabled :
      self.set_alarm( )
    else: 
      self.should_interrupt = True
      self.kill_alarm()

  
  #########################################################
  def new_wknd( self, entity, attributes, old, new, kwargs ):
    self.log( "Alarm on weekends switched to {}".format( new ) )
    self.weekends_enabled = new == "on"
 
  #########################################################
  def set_alarm( self ):
    self.kill_alarm()
    alarm_time   = ( self.alarm_time - self.pre_trip ).time()
    self.alarm_h = self.run_daily( self.sequence_lights, alarm_time )

  def kill_alarm( self ):
    if( self.alarm_h ): 
      self.cancel_timer( self.alarm_h )
      self.alarm_h = False
    


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


 
  ##########################################################
  def sequence_lights( self, kwargs ) : 

    ## Check to see if it's a weekend and needs to be ignored
    is_weekend = self.date().weekday() >=5     # weekdays are 0:4
    if is_weekend and not self.weekends_enabled: return

    self.log( "Alarm trip ... starting sequence" )

    #If the light is already up, abort
    min_level = 0
    self.current_level = {}

    for light in self.active_lights:
      level = self.get_state( light, attribute='brightness' )
      if not level: level = 0
      self.current_level[ light ] = level     #cache the current level for dim calc

      if level > (255/2):
        self.log( "Room already lit to {}... aborting".format( level ) )
        return  
      
      #Brightest light in the room...used to set starting point
      if level > min_level: 
        min_level = level 

    #Level the lights if so required
    if self.mode is dim_mode.scale and len( self.active_lights ) > 1:
      for light in self.active_lights:
        self.current_level[ light ] = min_level
        self.call_service( "light/turn_on", entity_id = light, brightness = min_level )
        
    
    #Compute the lighting stages
    self.time_delta = 1   # 1 minute time delta between steps    
    self.light_delta = {}
    self.stages      = (self.pre_trip.seconds / 60) / self.time_delta

    for light in self.active_lights:
      starting_level            = self.current_level[ light ]
      ending_level              = 255
      self.light_delta[ light ] = ( ending_level - starting_level ) / self.stages

    #Run the first adjustment and schedule the next one
    self.current_stage = 1
    self.set_lights( None )

  ##########################################################################
  def set_lights( self, kwargs ):

    #abort signal
    if self.should_interrupt:
      self.log("Interrupt signal received.  Aborting")
      self.should_interrupt = False
      return

    #set the lights
    for light in self.active_lights:
      new_level = self.current_level[ light ] + self.light_delta[ light ]
      self.log( "Adjusting {} to {}".format( light, new_level ) )
      self.call_service( "light/turn_on", entity_id = light, brightness = new_level )
      self.current_level[ light ] = new_level      

    self.current_stage = self.current_stage + 1
   
    #schedule the next update
    if self.current_stage <= self.stages:
      self.light_thread = self.run_in( self.set_lights, self.time_delta*60 ) 
    else:
      self.log("All done")






