# -*- coding: utf-8 -*-
"""
syntax:
    pcr2netcdf -S date -E date - N mapstackname -I mapstack_folder 
               -O netcdf_name [-b buffersize]

-S startdate in "%d-%m-%Y %H:%M:%S" e.g. 31-12-1990 00:00:00
-E endDate in "%d-%m-%Y %H:%M:%S"
-N Mapstack-name (prefix)
   You can sepcify multiple input mapstack  to merge them into one netcdf
   e.g. -M P -M TEMP -M PET
-I input mapstack folder
-O output netcdf file
-b maxbuf - maximum number of timesteps to buffer before writing (default = 600)
-t timestep - (set timestep in seconds, default = 86400) Only 86400 and 3600 supported


This utility is made to simplify running wflow models with OpenDA. The
OpenDA link needs the forcing timeseries to be in netcdf format. Use this to convert
all the input mapstacks to netcdf.


(c) J. Schellekens

Created on Tue May 13 07:37:04 2014

based on GLOFRIS_utils.py by H Winsemius

"""

try:
    import  wflow.wflow_lib as wflow_lib
    import wflow.pcrut as pcrut
except ImportError:
    import  wflow_lib  as wflow_lib 
    import  pcrut as pcrut
    
import time
import datetime as dt
import getopt
import sys
from numpy import *
import netCDF4 as nc4
import osgeo.gdal as gdal
import os


def usage(*args):
    sys.stdout = sys.stderr
    for msg in args: print msg
    print __doc__
    sys.exit(0)


def readMap(fileName, fileFormat,logger):
    """ 
    Read geographical file into memory
    """
    import osgeo.gdal as gdal 
    # Open file for binary-reading
    mapFormat = gdal.GetDriverByName(fileFormat)
    mapFormat.Register()
    ds = gdal.Open(fileName)
    if ds is None:
        logger.error('Could not open ' + fileName + '. Something went wrong!! Shutting down')
        sys.exit(1)
        # Retrieve geoTransform info
    geotrans = ds.GetGeoTransform()
    originX = geotrans[0]
    originY = geotrans[3]
    resX    = geotrans[1]
    resY    = geotrans[5]
    cols = ds.RasterXSize
    rows = ds.RasterYSize
    x = linspace(originX+resX/2,originX+resX/2+resX*(cols-1),cols)
    y = linspace(originY+resY/2,originY+resY/2+resY*(rows-1),rows)
    # Retrieve raster
    RasterBand = ds.GetRasterBand(1) # there's only 1 band, starting from 1
    data = RasterBand.ReadAsArray(0,0,cols,rows)
    FillVal = RasterBand.GetNoDataValue()
    RasterBand = None
    ds = None
    return x, y, data, FillVal
    

def write_netcdf_timeseries(srcFolder, srcPrefix, trgFile, trgVar, trgUnits, trgName, timeList, logger,maxbuf=600):
    """
    Write pcraster mapstack to netcdf file. Taken from GLOFRIS_Utils.py
    
    - srcFolder - Folder with pcraster mapstack
    - srcPrefix - name of the mapstack
    - trgFile - target netcdf file
    - tgrVar - variable in nc file
    - trgUnits - units for the netcdf file
    - timeLists - list of times
    
    Optional argumenrs
    - maxbuf = 600: number of timesteps to buffer before writing
    
    """
    # Create a buffer of a number of timesteps to speed-up writing    

    bufsize = minimum(len(timeList),maxbuf)
    print bufsize
    timestepbuffer = zeros((bufsize,169,187))
    # if necessary, make trgPrefix maximum of 8 characters    
    if len(srcPrefix) > 8:
        srcPrefix = srcPrefix[0:8]
    # Open target netCDF file
    nc_trg = nc4.Dataset(trgFile, 'a',format="NETCDF4",zlib=True)
    # read time axis and convert to time objects
    time = nc_trg.variables['time']
    timeObj = nc4.num2date(time[:], units=time.units, calendar=time.calendar)
    try:
        nc_var = nc_trg.variables[trgVar]
    except:
        # prepare the variable
        nc_var = nc_trg.createVariable(trgVar, 'f4', ('time', 'lat', 'lon',), fill_value=-9999., zlib=True)
        nc_var.units = trgUnits
        nc_var.standard_name = trgName
    # now loop over all time steps, check the date and write valid dates to a list, write time series to PCRaster maps
    for nn, curTime in enumerate(timeList):
        idx = where(timeObj==curTime)[0]
        count = nn + 1
        below_thousand = count % 1000
        above_thousand = count / 1000
        # read the file of interest
        pcraster_file  = str(srcPrefix + '%0' + str(8-len(srcPrefix)) + '.f.%03.f') % (above_thousand, below_thousand)
        pcraster_path = os.path.join(srcFolder, pcraster_file)
        # write grid to PCRaster file
        x, y, data, FillVal = readMap(pcraster_path, 'PCRaster',logger)
        logger.debug("Adding time: " + str(curTime))
        data[data==FillVal] = nc_var._FillValue
        
        buffreset = (idx + 1) % maxbuf
        bufpos = (idx) % maxbuf
        #timestepbuffer[bufpos,:,:] =  flipud(data)
        # Weird, the flupud is no longer needed!!!!
        timestepbuffer[bufpos,:,:] =  data
        if buffreset == 0 or idx ==  bufsize -1:
            logger.debug("Writing buffer to file at: " + str(curTime) + " " + str(int(bufpos) + 1) + " timesteps")
            nc_var[idx-bufsize+1:idx+1,:,:] = timestepbuffer
        
    nc_trg.sync()
    nc_trg.close()

    
    
def prepare_nc(trgFile, timeList, x, y, metadata, logger, units='Days since 1900-01-01 00:00:00', calendar='gregorian'):
    """
    This function prepares a NetCDF file with given metadata, for a certain year, daily basis data
    The function assumes a gregorian calendar and a time unit 'Days since 1900-01-01 00:00:00'
    """
    import datetime as dt
    
    logger.info('Setting up "' + trgFile + '"')
    startDayNr = nc4.date2num(timeList[0], units=units, calendar=calendar)
    endDayNr   = nc4.date2num(timeList[-1], units=units, calendar=calendar)
    time       = arange(startDayNr,endDayNr+1)
    nc_trg     = nc4.Dataset(trgFile,'w',format="NETCDF4",zlib=True)

    logger.info('Setting up dimensions and attributes. lat: ' + str(len(y))+ " lon: " + str(len(x)))
    nc_trg.createDimension('time', 0) #NrOfDays*8
    nc_trg.createDimension('lat', len(y))
    nc_trg.createDimension('lon', len(x))
    DateHour = nc_trg.createVariable('time','f8',('time',))
    DateHour.units = units
    DateHour.calendar = calendar
    DateHour.standard_name = 'time'
    DateHour.long_name = 'time'
    DateHour[:] = time
    y_var = nc_trg.createVariable('lat','f4',('lat',))
    y_var.standard_name = 'latitude'
    y_var.long_name = 'latitude'
    y_var.units = 'degrees_north'
    x_var = nc_trg.createVariable('lon','f4',('lon',))
    x_var.standard_name = 'longitude'
    x_var.long_name = 'longitude'
    x_var.units = 'degrees_east'
    y_var[:] = y
    x_var[:] = x
    projection= nc_trg.createVariable('projection','c')
    projection.long_name = 'wgs84'
    projection.EPSG_code = 'EPSG:4326'
    projection.proj4_params = '+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs'
    projection.grid_mapping_name = 'latitude_longitude'

    # now add all attributes from user-defined metadata
    for attr in metadata:
        nc_trg.setncattr(attr, metadata[attr])
    nc_trg.sync()
    nc_trg.close()




def date_range(start, end, tdelta="days"):
    
    if tdelta == "days":
        r = (end+dt.timedelta(days=1)-start).days
        return [start+dt.timedelta(days=i) for i in range(r)]
    else:
        r = (end+dt.timedelta(days=1)-start).days * 24
        return [start+dt.timedelta(hours=i) for i in range(r)]

 
def main(argv=None):
    """
    Perform command line execution of the model.
    """
    # initiate metadata entries
    metadata = {}
    metadata['title'] = 'wflow input mapstack'
    metadata['institution'] = 'Deltares'
    metadata['source'] = 'pcr2netcdf'
    metadata['history'] = time.ctime()
    metadata['references'] = 'http://wflow.googlecode.com'
    metadata['Conventions'] = 'CF-1.4'
     
    ncoutfile = "inmaps.nc"
    mapstackfolder="inmaps"
    mapstackname=[]
    var=[]
    varname=[]
    unit="mm"
    startstr="1-1-1990 00:00:00"
    endstr="2 2 1990 :00:00:00"
    mbuf=600
    timestepsecs = 86400
    
    clonemap=None
    
    if argv is None:
        argv = sys.argv[1:]
        if len(argv) == 0:
            usage()
            return    

    ## Main model starts here
    ########################################################################
    try:
        opts, args = getopt.getopt(argv, 'S:E:N:I:O:b:t:')
    except getopt.error, msg:
        usage(msg)

    for o, a in opts:
        if o == '-S': startstr = a
        if o == '-E': endstr = a
        if o == '-O': ncoutfile = a
        if o == '-I': mapstackfolder = a
        if o == '-b': mbuf = int(a)
        if o == '-t': 
            timestepsecs = int(a)
        if o == '-N': 
            mapstackname.append(a)
            var.append(a)
            varname.append(a)
    
    # USe first timestep as clone-map
    logger = pcrut.setlogger('pcr2netcdf.log','pcr2netcdf',thelevel=pcrut.logging.DEBUG)

    count = 1
    below_thousand = count % 1000
    above_thousand = count / 1000
    clonemapname  = str(mapstackname[0] + '%0' + str(8-len(mapstackname[0])) + '.f.%03.f') % (above_thousand, below_thousand)
    clonemap = os.path.join(mapstackfolder, clonemapname)
    pcrut.setclone(clonemap)
   
    x = pcrut.pcr2numpy(pcrut.xcoordinate(pcrut.boolean(pcrut.cover(1.0))),NaN)[0,:]
    y = pcrut.pcr2numpy(pcrut.ycoordinate(pcrut.boolean(pcrut.cover(1.0))),NaN)[:,0]
    

    start=dt.datetime.strptime(startstr,"%d-%m-%Y %H:%M:%S")
    end=dt.datetime.strptime(endstr,"%d-%m-%Y %H:%M:%S")
    if timestepsecs == 86400:
        timeList = date_range(start, end, tdelta="days")
    else:   
        timeList = date_range(start, end, tdelta="hours")

    
    prepare_nc(ncoutfile, timeList, x, y, metadata, logger)
    
    idx = 0
    for mname in mapstackname:
        logger.info("Converting mapstack: " + mname + " to " + ncoutfile)
        write_netcdf_timeseries(mapstackfolder, mname, ncoutfile, var[idx], unit, varname[idx], timeList, logger,maxbuf=mbuf)
        idx = idx + 1
    

if __name__ == "__main__":
    main()