from ..Script import Script
import re
from UM.Application import Application
class SwitchFil(Script):
    def __init__(self):
        super().__init__()
    
    def getSettingDataString(self):
        return """{
            "name":"Switch Filament ",
            "key": "SwitchFil",
            "metadata": {},
            "version": 2,
            "settings":
            {
                "pause_type":
                {
                    "label": "Changement",
                    "description": "Changement a la couche ou a la hauteur.",
                    "type": "enum",
                    "options": {"height":"Hauteur","layer":"Couche"},
                    "default_value": "height"
                },
                "pause_height":
                {
                    "label": "Hauteur",
                    "description": "Hauteur du changement.",
                    "unit": "mm",
                    "type": "float",
                    "default_value": 5.0,
                    "enabled": "pause_type == 'height'"
                },
                "pause_layer":
                {
                    "label": "Layer",
                    "description": "Couche du changement. (Min = 1).",
                    "unit": "",
                    "type": "int",
                    "minimum_value": "1",
                    "default_value": 25,
                    "enabled": "pause_type == 'layer'"
                },
         		"extruder":
                {
                    "label": "Sens",
                    "description": "Determine le filament qui sera introduit dans la tete.",
                    "unit": "mm",
                    "type": "enum",
					"options": {"1vers2":"1 vers 2","2vers1":"2 vers 1"},
                    "default_value": "1vers2"
                }
            }
        }"""
    
    #   Convenience function that finds the value in a line of g-code.
    #   When requesting key = x from line "G1 X100" the value 100 is returned.
    #   Override original function, which didn't handle values without a leading zero like ".3"
    #   Ignores keys found in comments (after ";"), but if you pass the semicolon in, you're good. eg. ";LAYER:"
    def getValue(self, line, key, default = None):
        if not key in line or (';' in line and line.find(key) > line.find(';')):
            return default
        sub_part = line[line.find(key) + len(key):]
        m = re.search('^[0-9]+\.?[0-9]*', sub_part)
        if m is None:
            m = re.search('^[0-9]*\.?[0-9]+', sub_part)
        if m is None:
            return default
        try:
            return float(m.group(0))
        except:
            return default
    
    def execute(self, data):
        # Initialize variables
        x = 0.
        y = 0.
        last_e = 0.
        last_e_temp = 0.
        current_z = 0.
        current_layer = 0.
        currently_in_custom = False
        # Get the user values into variables
        pause_type = self.getSettingValueByKey("pause_type")
        pause_z = self.getSettingValueByKey("pause_height")
        pause_layer = self.getSettingValueByKey("pause_layer")
        if Application.getInstance().getGlobalContainerStack().getProperty("machine_width", "value") < 450:
           park_x = 175
        else:
           park_x = 335

        park_y = Application.getInstance().getGlobalContainerStack().getProperty("machine_depth", "value")
		# Application.getInstance().getGlobalContainerStack().getProperty("machine_depth", "value")
        move_z = 0
        extr = self.getSettingValueByKey("extruder")
        retraction_mm = 4.5
        min_head_park_z = 25
        
        # Iterate through all the layers
        for layer in data:
            lines = layer.split("\n")
            # Iterate through the lines for each layer
            for line in lines:
                # Get the current LAYER number
                # They start at 0, so add 1
                l = self.getValue(line, ";LAYER:")
                if l is not None:
                    current_layer = l + 1
                
                # Skip lines inside of CUSTOM
                if 'CUSTOM' in line:
                    currently_in_custom = not currently_in_custom
                
                if currently_in_custom:
                    continue
                
                # We're not inside 'CUSTOM', now start processing
                # Get the E (extrusion) value from the current line. Will be None if none.
                e = self.getValue(line, "E")
                # Remember the last highest E (extrusion) value so that we can resume there after a pause
                if e is not None and e > last_e:
                    last_e = e
                
                # Get the current extruder temp
                # Get the M (RepRap command) value from the current line.  Will be None if none.
                m = self.getValue(line, "M")
                if m is not None and (m == 104 or m == 109):
                    # Get the S (command parameter) value
                    s = self.getValue(line, "S")
                    if s is not None:
                        last_e_temp = s
                
                # Get the G value. G0 and G1 are moves. Will be None if none.
                g = self.getValue(line, "G")
                
                # Catch resetting extruder value
                if g == 92:
                    x = self.getValue(line, "X")
                    y = self.getValue(line, "Y")
                    z = self.getValue(line, "Z")
                    if e is None and x is None and y is None and z is None: 
                        last_e = 0.
                    if e is not None:
                        last_e = e
                
                if g == 1 or g == 0:
                    # It was a move, get the X and Y values from the move line
                    x = self.getValue(line, "X")
                    y = self.getValue(line, "Y")
                    
                    # Not every line will have a Z value, but at least the first move on each layer will have one when it moves to that Z height. If we record the Z value, that will always be our current Z height
                    # Get the Z value. Will be None if none
                    current_z = self.getValue(line, "Z")
                    
                    # If we have a height, and we're at least at the first layer, and we're moving, then it's time to see if we should pause
                    if current_layer > 0 and current_z is not None and x is not None and y is not None:
                        # If the current height >= where they want to pause, then we want to pause before we do the next move
                        if (pause_type == 'height' and current_z >= pause_z) or (pause_type == 'layer' and current_layer >= pause_layer):
                            # We need to know where in the file we are in relation to layer and line so we can insert some stuff there
                            data_index = data.index(layer)
                            line_index = lines.index(line)
                            
                            # Build up the stuff that we're going to insert
                            # Gcode comments start with semi colon
                            # Put in a TYPE:CUSTOM header just so they know who (the script) added the following Gcode
                            prepend_gcode = ";TYPE:CUSTOM\n"
                            prepend_gcode += ";added code by post processing\n"
                            prepend_gcode += ";script: SwitchFil.py\n"
                            prepend_gcode += ";current z: %f\n" % (current_z)
                            
                            # Retraction
                            prepend_gcode += "M83  ;Set extruder to relative mode\n"
                            prepend_gcode += "G1 E-%f F10200  ;Retract\n" % (retraction_mm)
                            
                            # Move nozzle away from the bed so they can get their fingers under the nozzle
                            # Don't allow negative moveZ value. That would be bad. They would hit their print.
                            if move_z < 0:
                                move_z = 0
                            
                            new_z = 0
                            # Always move up to at least min z park value
                            if current_z + move_z < min_head_park_z:
                                new_z = min_head_park_z
                            else:
                                # We're getting the Max Z value from their print settings to make sure we don't go higher than their printer allows
                                # For Safety Leave a 10mm space (endstop)
                                max_z = Application.getInstance().getGlobalContainerStack().getProperty("machine_height", "value") - 10
                                new_z = current_z + move_z
                                if new_z > max_z:
                                    new_z = max_z
                            
                            # Move X and Y
                            # Don't allow negative park values
                            if park_x < 0:
                                park_x = 0
                            if park_y < 0:
                                park_y = 0
                            # We're getting the Max X and Y values to make sure we don't go off the bed
                            # For Safety Leave a 10mm space (endstop)
                            max_x = Application.getInstance().getGlobalContainerStack().getProperty("machine_width", "value")
                            # For Safety Leave a 10mm space (endstop)
                            max_y = Application.getInstance().getGlobalContainerStack().getProperty("machine_depth", "value")
                            # Make sure x and y are within machine range                            
                            if park_x > max_x:
                                park_x = max_x
                            if park_y > max_y:
                                park_y = max_y                          

                          # Move the head away
                            prepend_gcode += "G1 Z%f F300\n" % (current_z + 1)
                            prepend_gcode += "G1 X%f Y%f F9000\n" % (park_x, park_y)
                            prepend_gcode += "G1 E9 F400\n"
                            prepend_gcode += "G1 E-7 F500\n"
                            prepend_gcode += "G1 E4.5 F5000\n"
                            prepend_gcode += "G0 E-90.5 F10200\n"
                            if extr == '1vers2':
                                prepend_gcode += "T1\n"
                            if extr == '2vers1':
                                prepend_gcode += "T0\n"

                            prepend_gcode += "G1 E91 F1800\n"
                            prepend_gcode += "G1 E2 F200\n"
                            prepend_gcode += "G1 E-3 F10000\n"
                            prepend_gcode += "G1 E3 F10000\n"
                            prepend_gcode += "G1 E35 F200\n"
                            prepend_gcode += "G1 E-%f F6000\n" % (retraction_mm)
                            prepend_gcode += "G1 Y%f F4000\n" % (park_y-20)
                            
                            
                            
                            # Move the head back
                            prepend_gcode += "G1 X%f Y%f Z%f F9000  ;Move to next layer position\n" % (x, y, current_z)
                            prepend_gcode += "G1 E%f F10200\n" % (retraction_mm)
                            prepend_gcode += "G1 F9000\n"

                            prepend_gcode += "M82  ;Set extruder back to absolute mode\n"
                            prepend_gcode += "G92  E%f  ;Set the extrude value to the previous (before last retraction)\n" % (last_e)                

                            beginning = lines[:line_index]
                            ending = lines[line_index:]
                            layer = "\n".join(beginning) + "\n" + prepend_gcode + "\n".join(ending) + "\n"
                            
                            data[data_index] = layer #Override the data of this layer with the modified data
                            
                            #We're done. We inserted our gcode. Now finish up.
                            return data
                        # Continue to the next line
                        continue
        
        # We never found it. Just return the data unchanged.
        return data
