import math
from opentrons.types import Point
from opentrons import protocol_api
import time
import os
import numpy as np
from timeit import default_timer as timer
import json
from datetime import datetime
import csv

# metadata
metadata = {
    'protocolName': 'Kingfisher Pathogen setup - sample + beads + buffer preparation',
    'author': 'Aitor Gastaminza, Eva Gonzalez, José Luis Villanueva (jlvillanueva@clinic.cat)',
    'source': 'Hospital Clínic Barcelona',
    'apiLevel': '2.0',
    'description': 'Protocol for RNA extraction preparation for ThermoFisher Pathogen kit'
}

#Defined variables
##################
NUM_SAMPLES = 16
air_gap_vol = 15
temperature = 25  # Temperature of temp module
MS_vol=5

# mag_height = 11 # Height needed for NUNC deepwell in magnetic deck
mag_height = 17  # Height needed for ABGENE deepwell in magnetic deck
temperature = 4
L_deepwell = 8  # Deepwell side length (KingFisher deepwell)
x_offset_rs = 1 #Offset of the pickup when magnet is ON
volume_cone = 50  # Volume in ul that fit in the screwcap cone
diameter_screwcap = 8.25  # Diameter of the screwcap
volume_screw_one = 2000  # Total volume of first screwcap
volume_screw_two = 0  # Total volume of second screwcap
area_section_screwcap = (np.pi * diameter_screwcap**2) / 4
h_cone = (volume_cone * 3 / area_section_screwcap)

#Calculated variables
deepwell_cross_section_area = L_deepwell**2  # deepwell cross secion area
num_cols = math.ceil(NUM_SAMPLES / 8)  # Columns we are working on

# 'kf_96_wellplate_2400ul'
def run(ctx: protocol_api.ProtocolContext):
    ctx.comment('Actual used columns: ' + str(num_cols))
    STEP = 0
    STEPS = {  # Dictionary with STEP activation, description, and times
        1: {'Execute': False, 'description': 'Mix beads'},
        2: {'Execute': False, 'description': 'Transfer beads'},
        3: {'Execute': False, 'description': 'Add MS2'}
    }

    """
    # No wait time
    for s in STEPS:  # Create an empty wait_time
        if 'wait_time' not in STEPS[s]:
            STEPS[s]['wait_time'] = 0
    """
    folder_path = '/var/lib/jupyter/notebooks'
    if not ctx.is_simulating():
        if not os.path.isdir(folder_path):
            os.mkdir(folder_path)
        file_path = folder_path + '/Station_KB_sample_prep_pathogen_log.txt'

    # Define Reagents as objects with their properties
    class Reagent:
        def __init__(self, name, rinse,h_cono, v_fondo,
                     reagent_reservoir_volume_1,reagent_reservoir_volume_2,
                      num_wells= 1, tip_recycling=None):
            self.name = name
            self.rinse = bool(rinse)
            self.flow_rate_aspirate = 1
            self.flow_rate_dispense = 1
            self.reagent_reservoir_volume_1 = reagent_reservoir_volume_1
            self.reagent_reservoir_volume_2 = reagent_reservoir_volume_2
            self.col = 0
            self.vol_well = self.reagent_reservoir_volume_1
            self.h_cono = h_cono
            self.v_cono = v_fondo
            self.tip_recycling = tip_recycling
            self.unused_one=0
            self.unused_two=0
            self.vol_well_original = reagent_reservoir_volume / num_wells

    # Reagents and their characteristics
    Sample = Reagent(name='Sample',
                      flow_rate_aspirate=0.5,
                      flow_rate_dispense=1,
                      rinse=True,
                      reagent_reservoir_volume_1=460*96,
                      reagent_reservoir_volume_2=0,
                      h_cono=1.95,
                      v_fondo=35)

    Beads = Reagent(name='Magnetic beads and Lysis',
                    flow_rate_aspirate=1,
                    flow_rate_dispense=1.5,
                    rinse=True,
                    num_wells=4,
                    reagent_reservoir_volume_1=260*96*1.1,
                    reagent_reservoir_volume_2=0,
                    h_cono=1.95,
                    v_fondo=695 ) # Prismatic)

    MS = Reagent(name='MS2',
                    flow_rate_aspirate=1,
                    flow_rate_dispense=1.5,
                    rinse=False,
                    reagent_reservoir_volume=2000,
                    h_cono=h_cone,
                    v_fondo=volume_cone  # V cono
                    ) # Prismatic)

    Sample.vol_well = Sample.reagent_reservoir_volume_1
    Beads.vol_well = Beads.vol_well_original
    MS.vol_well = MS.reagent_reservoir_volume_1

    def distribute_custom(pipette, volume, src, dest,  pickup_height, extra_dispensal,*waste_pool):
        # Custom distribute function that allows for blow_out in different location and adjustement of touch_tip
        pipette.aspirate((len(dest) * volume) +
                         extra_dispensal, src.bottom(pickup_height))
        pipette.touch_tip(speed=20, v_offset=-5)
        pipette.move_to(src.top(z=5))
        pipette.aspirate(5)  # air gap
        for d in dest:
            pipette.dispense(5, d.top())
            pipette.dispense(volume, d)
            pipette.move_to(d.top(z=5))
            pipette.aspirate(5)  # air gap
        if waste_pool is not None:
            try:
                pipette.blow_out(waste_pool.wells()[0].bottom(pickup_height + 3))
            except:
                pipette.blow_out(waste_pool.bottom(pickup_height + 3))
        return (len(dest) * volume)

    def custom_mix(pipet, reagent, location, vol, rounds, blow_out, mix_height,x_offset=[0,0],source_height=3):
        '''
        Function for mix in the same location a certain number of rounds. Blow out optional
        x_offset=[source,destination]
        '''
        if mix_height == 0:
            mix_height = 3
        pipet.aspirate(1, location=location.bottom(
            z=source_height).move(Point(x=x_offset[0])), rate=reagent.flow_rate_aspirate)
        for _ in range(rounds):
            pipet.aspirate(vol, location=location.bottom(
                z=source_height).move(Point(x=x_offset[0])), rate=reagent.flow_rate_aspirate)
            pipet.dispense(vol, location=location.bottom(
                z=mix_height).move(Point(x=x_offset[1])), rate=reagent.flow_rate_dispense)
        pipet.dispense(1, location=location.bottom(
            z=mix_height).move(Point(x=x_offset[1])), rate=reagent.flow_rate_dispense)
        if blow_out == True:
            pipet.blow_out(location.top(z=-2))  # Blow out

    def calc_height(reagent, cross_section_area, aspirate_volume):
        nonlocal ctx
        ctx.comment('Remaining volume ' + str(reagent.vol_well) +
                    '< needed volume ' + str(aspirate_volume) + '?')
        if reagent.vol_well < aspirate_volume:
            ctx.comment('Next column should be picked')
            ctx.comment('Previous to change: ' + str(reagent.col))
            # column selector position; intialize to required number
            reagent.col = reagent.col + 1
            ctx.comment(str('After change: ' + str(reagent.col)))
            reagent.vol_well = reagent.vol_well_original
            ctx.comment('New volume:' + str(reagent.vol_well))
            height = (reagent.vol_well - aspirate_volume - reagent.v_cono) / cross_section_area
                    #- reagent.h_cono
            reagent.vol_well = reagent.vol_well - aspirate_volume
            ctx.comment('Remaining volume:' + str(reagent.vol_well))
            if height < 0.5:
                height = 0.5
            col_change = True
        else:
            height = (reagent.vol_well - aspirate_volume - reagent.v_cono) / cross_section_area #- reagent.h_cono
            reagent.vol_well = reagent.vol_well - aspirate_volume
            ctx.comment('Calculated height is ' + str(height))
            if height < 0.5:
                height = 0.5
            ctx.comment('Used height is ' + str(height))
            col_change = False
        return height, col_change

    def move_vol_multi(pipet, reagent, source, dest, vol, air_gap_vol, x_offset,
                       pickup_height, rinse, disp_height = -2, multi = False):
        '''
        x_offset: list with two values. x_offset in source and x_offset in destination i.e. [-1,1]
        pickup_height: height from bottom where volume
        disp_height: dispense height; by default it's close to the top, but in case it is needed it can be lowered
        rinse: if True it will do 2 rounds of aspirate and dispense before the tranfer
        '''
        # Rinse before aspirating
        if rinse == True:
            custom_mix(pipet, reagent, location = source, vol = vol,
                       rounds = 2, blow_out = True, mix_height = 0)
        # SOURCE
        s = source.bottom(pickup_height).move(Point(x = x_offset[0]))
        pipet.aspirate(vol, s)  # aspirate liquid
        if air_gap_vol != 0:  # If there is air_gap_vol, switch pipette to slow speed
            pipet.aspirate(air_gap_vol, source.top(z = -2),
                           rate = reagent.flow_rate_aspirate)  # air gap
        # GO TO DESTINATION
        drop = dest.top(z = disp_height).move(Point(x = x_offset[1]))
        pipet.dispense(vol + air_gap_vol, drop,
                       rate = reagent.flow_rate_dispense)  # dispense all
        pipet.blow_out(dest.top(z = -2))
        if multi == True:
            if air_gap_vol != 0: #Air gap for multidispense
                pipet.aspirate(air_gap_vol, dest.top(z = -2),
                               rate = reagent.flow_rate_aspirate)  # air gap

####################################
    # load labware and modules
    # 12 well rack
    reagent_res = ctx.load_labware(
        'nest_12_reservoir_15ml', '2', 'Reagent deepwell plate')

##################################
    # Elution plate - final plate, goes to C
    sample_plate = ctx.load_labware(
        'kf_96_wellplate_2400ul','1',
        'Deepwell sample plate')
####################################
    # load labware and modules
    # 12 well rack
    tuberack = ctx.load_labware(
        'opentrons_24_aluminumblock_generic_2ml_screwcap', '3',
        'Bloque Aluminio 24 Screwcap')
##################################

    # pipettes. P1000 currently deactivated
    m300 = ctx.load_instrument(
        'p300_multi_gen2', 'right', tip_racks=tips200)  # Load multi pipette
    p20 = ctx.load_instrument('p20_single_gen2', 'left', tip_racks=tips20) # load P1000 pipette

    # Load Tipracks
    tips20 = [
        ctx.load_labware('opentrons_96_filtertiprack_20ul', slot)
        for slot in ['5']
    ]

    tips200 = [
        ctx.load_labware('opentrons_96_filtertiprack_200ul', slot)
        for slot in ['6']
    ]

    Beads.reagent_reservoir = reagent_res.rows()[0][:Beads.num_wells]  # 1 row, 4 columns (first ones)
    work_destinations = sample_plate.rows()[0][:Elution.num_wells]
    # Declare which reagents are in each reservoir as well as deepwell and elution plate
    MS.reagent_reservoir = tuberack.rows()[0][0] # 1 row, 2 columns (first ones)

    ############################################################################
    # STEP 1: PREMIX BEADS
    ############################################################################
    STEP += 1
    if STEPS[STEP]['Execute'] == True:

        start = datetime.now()
        ctx.comment('Step ' + str(STEP) + ': ' + STEPS[STEP]['description'])
        ctx.comment('###############################################')
        if not m300.hw_pipette['has_tip']:
            pick_up(m300)  # These tips are reused in the first transfer of beads
            ctx.comment('Tip picked up')
        ctx.comment('Mixing ' + Beads.name)

        # Mixing
        custom_mix(m300, Beads, Beads.reagent_reservoir[Beads.col], vol=180,
                   rounds=10, blow_out=True, mix_height=0)
        ctx.comment('Finished premixing!')
        ctx.comment('Now, reagents will be transferred to deepwell plate.')

        end = datetime.now()
        time_taken = (end - start)
        ctx.comment('Step ' + str(STEP) + ': ' +
                    STEPS[STEP]['description'] + ' took ' + str(time_taken))
        STEPS[STEP]['Time:'] = str(time_taken)

    ############################################################################
    # STEP 2: TRANSFER BEADS
    ############################################################################
    STEP += 1
    if STEPS[STEP]['Execute'] == True:
        # Transfer parameters
        start = datetime.now()
        ctx.comment('Step ' + str(STEP) + ': ' + STEPS[STEP]['description'])
        ctx.comment('###############################################')
        beads_transfer_vol = [130, 130]  # Two rounds of 155
        x_offset = 0
        rinse = True
        for i in range(num_cols):
            if not m300.hw_pipette['has_tip']:
                pick_up(m300)
            for j, transfer_vol in enumerate(beads_transfer_vol):
                # Calculate pickup_height based on remaining volume and shape of container
                [pickup_height, change_col] = calc_height(
                    Beads, multi_well_rack_area, transfer_vol * 8)
                if change_col == True:  # If we switch column because there is not enough volume left in current reservoir column we mix new column
                    ctx.comment(
                        'Mixing new reservoir column: ' + str(Beads.col))
                    custom_mix(m300, Beads, Beads.reagent_reservoir[Beads.col],
                               vol=180, rounds=10, blow_out=True, mix_height=0)
                ctx.comment(
                    'Aspirate from reservoir column: ' + str(Beads.col))
                ctx.comment('Pickup height is ' + str(pickup_height))
                if j != 0:
                    rinse = False
                move_vol_multi(m300, reagent=Beads, source=Beads.reagent_reservoir[Beads.col],
                               dest=work_destinations[i], vol=transfer_vol, air_gap_vol=air_gap_vol, x_offset=[x_offset,0],
                               pickup_height=pickup_height, rinse=rinse)

            ctx.comment('Mixing sample with beads ')
            #custom_mix(m300, Beads, location=work_destinations[i], vol=180,rounds=6, blow_out=True, mix_height=16)
            m300.drop_tip(home_after=False)
            # m300.return_tip()
            tip_track['counts'][m300] += 8
        end = datetime.now()
        time_taken = (end - start)
        ctx.comment('Step ' + str(STEP) + ': ' +
                    STEPS[STEP]['description'] + ' took ' + str(time_taken))
        STEPS[STEP]['Time:'] = str(time_taken)

        ctx.comment('Now incubation will start ')

    ############################################################################
    # STEP 3: Transfer MS
    ############################################################################
    STEP += 1
    if STEPS[STEP]['Execute'] == True:
        start = datetime.now()
        p20.pick_up_tip()
        tip_track['counts'][p20]+=1
        used_vol=[]
        for dest in sample_plate.wells():

            [pickup_height,col_change]=calc_height(MS, area_section_screwcap, MS_vol)
            # source MMIX_reservoir[col_change]
            used_vol_temp = distribute_custom(p20, MS_vol, MS.reagent_reservoir,
                dest,pickup_height, extra_dispensal=0)

            used_vol.append(used_vol_temp)

        p300.drop_tip()
        MMIX.unused_two = MMIX.vol_well

        end = datetime.now()
        time_taken = (end - start)
        ctx.comment('Step ' + str(STEP) + ': ' +
                    STEPS[STEP]['description'] + ' took ' + str(time_taken))
        STEPS[STEP]['Time:'] = str(time_taken)