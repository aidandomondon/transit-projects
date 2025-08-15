import requests
import gtfs_realtime_NYCT_pb2 as nyct
from gtfs_realtime_NYCT_pb2 import gtfs__realtime__pb2 as gtfs
from datetime import datetime, timedelta
import streamlit as st
from pydeck.bindings import Deck, Layer, ViewState
from pydeck.types import String
import pandas as pd

SEVEN_TRAIN_PURPLE = {
    'hex': '#9A38A1',
    'rgba': (154, 56, 161, 255)
}

SUBWAY_REALTIME_API_ENDPOINT = r'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs'

resp = requests.get(
    url=SUBWAY_REALTIME_API_ENDPOINT
).content

# vehicle_position = gtfs.VehiclePosition()
# vehicle_position.ParseFromString(resp)

# print(gtfs.VehiclePosition.VehicleStopStatus.Name(vehicle_position.current_status))
# print(gtfs.VehiclePosition.CongestionLevel.Name(vehicle_position.congestion_level))
# print(gtfs.VehiclePosition.OccupancyStatus.Name(vehicle_position.occupancy_status))
# print(vehicle_position.timestamp)

# trip_descriptor = nyct.NyctTripDescriptor()
# trip_descriptor.ParseFromString(resp)
# print(nyct.NyctTripDescriptor.Direction.Name(trip_descriptor.direction))

# trip_descriptor = gtfs.TripDescriptor()
# trip_descriptor.ParseFromString(resp)
# print(trip_descriptor.start_time.decode())

# trip_update = gtfs.TripUpdate()
# trip_update.ParseFromString(resp)
# print(trip_update.timestamp)

# stop_time_update = gtfs.TripUpdate.StopTimeUpdate()
# stop_time_update.ParseFromString(resp)
# print(stop_time_update.arrival)



feed_message = gtfs.FeedMessage()
feed_message.ParseFromString(resp)

# Feed Entities pertain to vehicles when their vehicle attribute 
# is not empty (is not equal to an empty Vehicle Position)
def vehicle_info_json(vehicle: gtfs.VehiclePosition) -> object:
    return {
        "time": datetime.fromtimestamp(vehicle.timestamp),
        "trip": trip_info_json(vehicle.trip),
        "current_status": gtfs.VehiclePosition.VehicleStopStatus.Name(vehicle.current_status),
        "stop_id": vehicle.stop_id
    }

def trip_info_json(trip: gtfs.TripDescriptor) -> object:
    nyct_trip = trip.Extensions[nyct.nyct_trip_descriptor]
    type_and_line, decoded_origin_type, origin_and_destination = nyct_trip.train_id.split()
    return {
        "trip_id": trip.trip_id,
        "line": type_and_line[1],
        "origin": origin_and_destination.split('/')[0],
        "destination": origin_and_destination.split('/')[1],
        "direction": nyct.NyctTripDescriptor.Direction.Name(nyct_trip.direction)
    }

##########################
# Plot lines between stops
##########################
shapes = pd.read_csv('./src/gtfs_subway/shapes.txt', index_col='shape_id')
shape_7_local = shapes.loc['7..N95R'].sort_values(by='shape_pt_sequence').loc[
    :, 
    ['shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence']
]
shape_7_local['next_shape_pt_lat'] = shape_7_local['shape_pt_lat'].shift(-1)
shape_7_local['next_shape_pt_lon'] = shape_7_local['shape_pt_lon'].shift(-1)

############
# Plot stops
############
trips = pd.read_csv('./src/gtfs_subway/trips.txt')
all_7_trip_ids = trips.loc[trips['route_id'] == '7', 'trip_id'].unique()

stop_times = pd.read_csv('./src/gtfs_subway/stop_times.txt')
all_7_stop_ids = stop_times.loc[stop_times['trip_id'].isin(all_7_trip_ids), 'stop_id'].unique()

stops = pd.read_csv('./src/gtfs_subway/stops.txt')
all_7_stops = stops.loc[stops['stop_id'].isin(all_7_stop_ids)]

####################################
# Plot number of trains at each stop
####################################

all_7_train_position_entities = []
for entity in feed_message.entity:
    # Ignore non-vehicle entities
    if entity.vehicle == gtfs.VehiclePosition():
        continue
    vehicle = vehicle_info_json(entity.vehicle)
    # Focus on 7 train
    if vehicle['trip']['line'] != '7':
        continue
    all_7_train_position_entities.append(vehicle)


all_7_train_position_entities: pd.DataFrame = pd.DataFrame.from_dict(data=all_7_train_position_entities)
# Get trip id
all_7_train_position_entities['trip_id'] = all_7_train_position_entities['trip'].apply(lambda trip: trip['trip_id'])
all_7_train_position_entities = all_7_train_position_entities.sort_values(by='time', ascending=False).drop_duplicates('trip_id', keep='first')
# Get direction
all_7_train_position_entities['direction'] = all_7_train_position_entities['trip'].apply(lambda trip: trip['direction'])
# Filter out old vehicle position updates
time_of_latest_update: datetime = all_7_train_position_entities['time'].iloc[0]
all_7_train_position_entities = all_7_train_position_entities.loc[
    time_of_latest_update - all_7_train_position_entities['time'] < timedelta(minutes=1)
]

all_7_train_positions = all_7_train_position_entities.merge(
    all_7_stops, 
    on='stop_id'
)[['trip_id', 'current_status', 'direction', 'parent_station', 'stop_name', 'stop_lat', 'stop_lon']].sort_values(
    by='parent_station'
).groupby(
    by=['parent_station', 'current_status', 'direction']
).agg(
    num_trains=('trip_id', 'count'),
)

def get_coordinates(parent_station: str, 
                    current_status: gtfs.VehiclePosition.VehicleStopStatus, 
                    direction: nyct.NyctTripDescriptor.Direction) -> tuple[float, float]:
    if current_status == gtfs.VehiclePosition.VehicleStopStatus.STOPPED_AT:
        lat, lon = stops.loc[
            stops['parent_station'] == parent_station, 
            ['stop_lat', 'stop_lon']
        ].astype('float').drop_duplicates().values[0]
    
    else:
        buffer = 1 if current_status == gtfs.VehiclePosition.VehicleStopStatus.INCOMING_AT else 5
        if direction == nyct.NyctTripDescriptor.Direction.NORTH or parent_station == '701':
            buffer *= -1
        next_stop_lat, next_stop_lon = stops.loc[
            stops['parent_station'] == parent_station, 
            ['stop_lat', 'stop_lon']
        ].astype('float').drop_duplicates().values[0]
        next_stop_shape_sequence_number: int = shape_7_local.loc[
            (shape_7_local['shape_pt_lat'] == next_stop_lat)
                & (shape_7_local['shape_pt_lon'] == next_stop_lon),
            'shape_pt_sequence'
        ].values[0]
        display_pt_sequence_number: int = next_stop_shape_sequence_number + buffer
        try:
            lat, lon = shape_7_local.loc[
                shape_7_local['shape_pt_sequence'] == display_pt_sequence_number,
                ['shape_pt_lat', 'shape_pt_lon']
            ].drop_duplicates().values[0]
        except IndexError as e:
            print(
                str(current_status), 
                str(parent_station), 
                str(direction), 
                next_stop_shape_sequence_number, 
                display_pt_sequence_number
            )
            raise e
    return lat, lon

# Dataframe for plotting active trains on map 
all_7_train_positions_display = all_7_train_positions.reset_index()
# Use customized coordinates to represent in-progress and incoming trains
all_7_train_positions_display['lat'], all_7_train_positions_display['lon'] = tuple(zip(*all_7_train_positions_display.apply(
    lambda row: get_coordinates(
        row['parent_station'],
        getattr(gtfs.VehiclePosition.VehicleStopStatus, row['current_status']),
        getattr(nyct.NyctTripDescriptor.Direction, row['direction'])
    ),
    axis=1
)))

# Get English station names
all_7_train_positions_display = all_7_train_positions_display.merge(
    stops[['parent_station', 'stop_name']].drop_duplicates(), how='left', on='parent_station'
)
# Format columns to contain the text that will be displayed rather than raw data
all_7_train_positions_display['num_trains'] = all_7_train_positions_display['num_trains'].apply(
    lambda num: f"{num} train" + ("s" if num > 1 else "")
)
all_7_train_positions_display['current_status'] = all_7_train_positions_display['current_status'].apply(
    lambda status: status.lower().replace('_', ' ')
)

st.title('7 Train')
st.text('Desktop: hold shift and move mouse to rotate view')
st.pydeck_chart(
    Deck(
        map_provider='google_maps',
        map_style=None,
        initial_view_state=ViewState(
            latitude=40.747786461448925,
            longitude=-73.9020397548519,
            zoom=12,
            pitch=0,
        ),
        layers=[
            Layer(
                "ArcLayer",
                data=shape_7_local.dropna(),
                getHeight=0,
                getSourcePosition=['shape_pt_lon', 'shape_pt_lat'],
                getTargetPosition=['next_shape_pt_lon', 'next_shape_pt_lat'],
                getSourceColor=SEVEN_TRAIN_PURPLE['rgba'],
                getTargetColor=SEVEN_TRAIN_PURPLE['rgba'],
                getWidth=3,
            ),
            Layer(
                "ScatterplotLayer",
                data=all_7_stops,
                get_position="[stop_lon, stop_lat]",
                filled=False,
                stroked=True,
                get_line_color=SEVEN_TRAIN_PURPLE['rgba'],
                pickable=False,
                radius_min_pixels=10,
                radius_max_pixels=10,
                line_width_min_pixels=3,
                line_width_max_pixels=3,
            ),
            Layer(
                "ScatterplotLayer",
                data=all_7_train_positions_display,
                get_position="[lon, lat]",
                filled=True,
                stroked=True,
                get_color=SEVEN_TRAIN_PURPLE['rgba'],
                pickable=True,
                radius_min_pixels=10,
                radius_max_pixels=10,
                line_width_min_pixels=3,
                line_width_max_pixels=3,
            )
        ],
        tooltip={
            "html": """\
<b>{num_trains} {current_status} {stop_name}</b>
<br/>
<b>Direction:&nbsp;</b>{direction}
""",
            "style": {
                "color": "white"
            }
        }
    )
)

# Add cone of light indicating train direction