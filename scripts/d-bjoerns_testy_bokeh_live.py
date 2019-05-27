# IMPORT MODULES
import time
import numpy as np
import holoviews as hv
import datashader as ds
from holoviews.operation.datashader import datashade

from holoviews import opts
from holoviews.streams import Pipe, RangeXY, PlotSize
import holoviews.plotting.bokeh
from tornado import gen

from bokeh.plotting import figure, curdoc
from bokeh.layouts import column, row
from functools import partial

from threading import Thread

import sqs_nqs_tools.online as online
import sqs_nqs_tools as tools

# MODULE CONFIGS
hv.extension('bokeh')
renderer = hv.renderer('bokeh')  # renderer to convert objects from holoviews to bokeh
renderer = renderer.instance(mode="server")
hv.output(dpi=300, size=100)
doc = curdoc()  # DOC for Bokeh Objects

# DATA SOURCE
#source = 'tcp://10.253.0.142:6666'  # LIVE
source = 'tcp://127.0.0.1:8011' # emulated live

# DATA CONFIG
N_datapts = 400000 # total number of TOF datapoints that are visualized
start_tof = 130000 # index of first TOF datapoint considered
## yielded config values
end_tof = start_tof+N_datapts # index of last TOF datapoint considered
x_tof = np.arange(start_tof,end_tof) # x-axis for tof data points

# Data handling functions
@gen.coroutine
def update_pipe(x,y):
    _pipe__TOF_single.send((x,y))

@online.pipeline
def processTofs(d):
    '''
    process tofs in pipeline
    '''
    d['tof'] = d['tof'][start_tof:end_tof] # cut out index range that we are interested in
    d['x_tof'] = x_tof # add values for x axis
    return d

class performanceMonitor():
    def __init__(self):
        import time
        self.t_start = time.time()
        self.t_start_loop = self.t_start
        self.for_loop_step_dur = 0
        self.n=-1
        self.freq_avg = 0
        self.dt_avg = 0
        self.trainId = 0
        self.trainId_old = -1
        self.skip_count = 0
        
    def iteration(self):
        self.n+=1
        self.dt = (time.time()-self.t_start)
        self.t_start = time.time()
        freq = 1/self.dt
        if self.n>0:
            self.dt_avg = (self.dt_avg * (self.n-1) + self.dt) / self.n
            freq_avg = 1/self.dt_avg
            loop_classification_percent = self.for_loop_step_dur/0.1*100
            if loop_classification_percent < 100:
                loop_classification_msg="OK"
            else:
                loop_classification_msg="TOO LONG!!!"
            print("Frequency: "+str(round(freq_avg,1)) +" Hz  |  skipped: "+str(self.skip_count)+" ( "+str(round(self.skip_count/self.n*100,1))+" %)  |  n: "+str(self.n)+"/"+str(self.trainId)+"  |  Loop benchmark: "+str(round(loop_classification_percent,1))+ " % (OK if <100%) - "+loop_classification_msg) 
        self.t_start_loop = time.time()
        
    def update_trainId(self,tid):
        self.trainId_old = self.trainId
        self.trainId = tid
        if self.n == 0:
            self.trainId_old = str(int(tid) -1)
        if int(self.trainId) - int(self.trainId_old) is not 1:
            self.skip_count +=1
            
    def time_for_loop_step(self):
        self.for_loop_step_dur = time.time()-self.t_start_loop

def makeDatastreamPipeline(source):
    ds = online.servedata(source) #get the datastream
    ds = online.getTof(ds) #get the tofs
    ds = processTofs(ds) #treat the tofs
    ds = online.getSomeDetector(ds, name='tid', spec0='SQS_DIGITIZER_UTC1/ADC/1:network', spec1='digitizers.trainId') #get current trainids from digitizer property
    return ds

def makeBigData():
    print("Source: "+ source) # print source set for data
    
    # Setup Data Stream Pipeline
    ds = makeDatastreamPipeline(source)
    
    perf = performanceMonitor() # outputs to console info on performance - eg what fraction of data was not pulled from live stream and thus missed
    
    for data in ds:
        # performance monitor - frequency of displaying data + loop duration
        perf.iteration()
        # Hand Data from datastream to plots and performance monitor
        # TOF
        x = np.squeeze(data['x_tof']); y = np.squeeze(data['tof'])
        doc.add_next_tick_callback(partial(update_pipe, x=x, y=y))
        # TrainId
        trainId = str(data['tid'])
        
        perf.update_trainId(trainId) # give current train id to performance monitor for finding skipping of shots
        perf.time_for_loop_step() # tell performance monitor that this is the end of the for loop


# Helper to convert from holoviews to bokeh
def hv_to_bokeh_obj(hv_layout):
    hv_plot = renderer.get_plot(hv_layout) 
    return hv_plot.state
    
# plot tools functions
def largeData_line_plot(pipe, width=1500, height=400,ylim=(-500, 40),xlim=(start_tof,start_tof+N_datapts), xlabel="index", ylabel="TOF signal", cmap = ['blue'], title=None):
    TOF_dmap = hv.DynamicMap(hv.Curve, streams=[pipe])
    TOF_dmap_opt = datashade(TOF_dmap, streams=[PlotSize, RangeXY], dynamic=True, cmap = cmap)
    return hv_to_bokeh_obj( TOF_dmap_opt.opts(width=width,height=height,ylim=ylim,xlim=xlim, xlabel=xlabel, ylabel=ylabel, title = title) )
    


# Data pipes and buffers for plots
_pipe__TOF_single = Pipe(data=[])
   
# SETUP PLOTS

# example for coupled plots
#         layout = hv.Layout(largeData_line_plot(_pipe__TOF_single, title="TOF single shots - LIVE") + largeData_line_plot(_pipe__TOF_single, title="TOF single shots - LIVE 2", cmap=['red'])).cols(1)
bokeh_live_tof =  largeData_line_plot(_pipe__TOF_single, title="TOF single shots - LIVE") 
bokeh_live_tof_duplicate = largeData_line_plot(_pipe__TOF_single, title="TOF single shots - LIVE", cmap=["red"])

# SET UP BOKEH LAYOUT
bokeh_layout = column(bokeh_live_tof,bokeh_live_tof_duplicate)

# add bokeh layout to current doc
doc.add_root(bokeh_layout)

# Start Thread for Handling of the Live Data Strem
thread = Thread(target=makeBigData)
thread.start()
