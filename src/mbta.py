import requests
from json import loads
import streamlit as st
import datetime

# Returns an object containing the JSON object returned by the
# specified API endpoint
def get_api_json_resp(url: str) -> object:
    resp = requests.get(url)
    content = resp.content
    json = loads(content)
    return json


#########################
# Define useful endpoints
#########################

TRIPS_ENDPOINT_URL="https://api-v3.mbta.com/trips/"

ROUTES_ENDPOINT_URL="https://api-v3.mbta.com/routes"
route_ids = [
    route['id'] for route 
    in get_api_json_resp(ROUTES_ENDPOINT_URL)['data']
]

STOPS_ENDPOINT_URL="https://api-v3.mbta.com/stops"
stop_attr_by_id = {
    stop['id']: stop['attributes'] for stop 
    in get_api_json_resp(STOPS_ENDPOINT_URL)['data']
}

# Using this endpoint instead of the V3 endpoint because V3 endpoint does not
# include the sequence numbers of the carriages in a vehicle, which are necessary to
# give occupancy percentage any meaning in the context of asset wear/damage.
VEHICLE_POSITIONS_ENDPOINT_URL="https://cdn.mbta.com/realtime/VehiclePositions.json"

ALERTS_ENDPOINT_URL="https://api-v3.mbta.com/alerts?route=Orange"


# Assumes that all active trips are those (and only those) associated with a current vehicle position
# Excludes non-revenue trips
def get_active_trip_ids() -> list[object]:
    resp_obj = get_api_json_resp(VEHICLE_POSITIONS_ENDPOINT_URL)
    entity = resp_obj['entity']
    return [
        vehicle_position['vehicle']['trip']['trip_id']
        for vehicle_position in entity
        if vehicle_position['vehicle']['trip']['route_id'] == 'Orange'
            and not vehicle_position['vehicle']['trip']['trip_id'].startswith('NONREV')
    ]


# Returns the VehicleDescriptor of the first VehiclePosition with the specified trip ID.
# Raises an Exception if no VehiclePosition can be found with the specified trip ID.
def get_vehicle(trip_id: str) -> object:
    header, entity = get_api_json_resp(VEHICLE_POSITIONS_ENDPOINT_URL).values()
    matching_vehicles = [    # vehicles matching trip ID
        vehicle_position['vehicle']
        for vehicle_position 
        in entity
        if vehicle_position['vehicle']['trip']['trip_id'] == trip_id
    ]
    if len(matching_vehicles) < 1:
        raise Exception(f"No VehiclePosition found with trip_id={trip_id}")
    return matching_vehicles[0]


def get_current_status(trip_id: str) -> str:
    vehicle = get_vehicle(trip_id)
    return vehicle['current_status']

def get_current_stop(trip_id: str) -> str:
    vehicle = get_vehicle(trip_id)
    return vehicle['stop_id']

def get_destination_name(trip_id: str) -> str:
    trip_resp_obj = get_api_json_resp(url=f"{TRIPS_ENDPOINT_URL}/{trip_id}")
    route = trip_resp_obj['data']['relationships']['route']
    route_id = route['data']['id']
    route_resp_obj = get_api_json_resp(url=f"{ROUTES_ENDPOINT_URL}/{route_id}")
    direction_id = int(trip_resp_obj['data']['attributes']['direction_id']) # e.g. "0" or "1"
    direction_destinations = route_resp_obj['data']['attributes']['direction_destinations'] # e.g. "Forest Hills" or "Oak Grove"
    destination = direction_destinations[direction_id]
    return destination

def get_carriage_details(trip_id: str) -> list:
    vehicle = get_vehicle(trip_id)
    return {
        carriage['carriage_sequence']: {
            'label': carriage['label'],
            'occupancy_status': carriage['occupancy_status'],
            'occupancy_percentage': carriage['occupancy_percentage'] if 'occupancy_percentage' in carriage.keys() else float('NaN')  
        }
        for carriage in vehicle['multi_carriage_details']
    }

def _parse_date(date_string: str) -> datetime.datetime:
    # remove colon separating hour and minute of timezone offset
    # so that it can be parsed by the %z directive
    date_string = date_string[:-3] + date_string[-2:]
    date_string = datetime.datetime.strptime(
        date_string, 
        "%Y-%m-%dT%H:%M:%S%z"
    )
    return date_string
def get_alerts() -> list[object]:
    # Sort by newest alerts first
    resp_obj = get_api_json_resp(ALERTS_ENDPOINT_URL + '&' + 'sort=-created_at')
    return [
        {
            'service_effect': alert['attributes']['service_effect'],
            'created_at': _parse_date(alert['attributes']['created_at']),
            'url': alert['attributes']['url'],
            'short_header': alert['attributes']['short_header'],
            'severity': alert['attributes']['severity']
        }
        for alert in resp_obj['data']
    ]


####################
# UI (Streamlit App)
####################
st.set_page_config(layout="wide")

def get_current_status_formatted(trip_id: str) -> str:
    return get_current_status(trip_id).replace('_', ' ').lower()
    
def get_current_stop_name(trip_id: str) -> str:
    current_stop_id = get_current_stop(trip_id)
    resp_obj = get_api_json_resp(url=f"{STOPS_ENDPOINT_URL}/{current_stop_id}")
    return resp_obj['data']['attributes']['name']

active_trip_ids = get_active_trip_ids()

st.title('MBTA Orange Line Asset Monitor')

st.divider()

st.header('Train Car Stress Monitor')
with st.container(border=True):
    SELECTED_TRIP_ID = st.radio(
        label='Select A Trip',
        options=active_trip_ids,
        index=0,
        horizontal=True
    )
    st.caption('Non-revenue trips are not displayed.')
    carriage_details = get_carriage_details(SELECTED_TRIP_ID)

st.subheader(f"Trip _{SELECTED_TRIP_ID}_")

with st.container(border=True):
    st.subheader('General Info', divider='grey')
    st.markdown(f"**Destination:** _{get_destination_name(SELECTED_TRIP_ID)}_")
    st.markdown(f"**Location:** {get_current_status_formatted(SELECTED_TRIP_ID)} _{get_current_stop_name(SELECTED_TRIP_ID)}_")

OCCUPANCY_STATUS_COLORS = {
    'EMPTY': "#00f2ffd5",
    'MANY_SEATS_AVAILABLE': '#b3ffb3',
    'FEW_SEATS_AVAILABLE': "#ffff99",
    'STANDING_ROOM_ONLY': "#ffc800",
    'CRUSHED_STANDING_ROOM_ONLY': "#f0837d",
    'FULL': "#ff00d0b4",
    'NOT_ACCEPTING_PASSENGERS': "#9b9b9b",
    'NO_DATA_AVAILABLE': '#9b9b9b',
    'NOT_BOARDABLE': '#9b9b9b'
}
def st_carriage_metric(label, occupancy_percentage, occupancy_status) -> None:
    color = OCCUPANCY_STATUS_COLORS[occupancy_status]
    st.markdown(
        f"""
            <div class="train">
                <div class="train-body"
                    style="
                        font-size:{CARRIAGE_SIZE_PX}px;
                        display:flex;
                        flex-direction: row;
                        justify-content:center;
                        align-items: center;
                        border-style:solid;
                        border-radius:25px;
                        background-color:{color}
                    "
                >
                    <div
                        style="
                            display:flex;
                            flex-direction: column;
                            justify-content:center;
                            align-items: center;
                        "
                    >
                        <p>{occupancy_percentage}<small>%</small></p>
                        <p style="font-size:20px;">Car #{label}</p>
                    </div>
                </div>
                <div 
                    class="train-wheels"
                    style="
                        display:flex;
                        flex-direction:row;
                        justify-content:space-evenly;
                    "
                >
                    <div
                        style="
                            height:{CARRIAGE_SIZE_PX // 4}px;
                            width:{CARRIAGE_SIZE_PX // 4}px;
                            border-style:solid;
                            border-radius:50px;
                            background-color:{color};
                        "
                    ></div>
                    <div 
                        style="
                            height:{CARRIAGE_SIZE_PX // 4}px;
                            width:{CARRIAGE_SIZE_PX // 4}px;
                            border-style:solid;
                            border-radius:50px;
                            background-color:{color};
                        "
                    ></div>
                </div>
            </div>
        """, 
        unsafe_allow_html=True
    )

with st.container(border=True):
    st.subheader('Live Occupancy Of Each Carriage', divider='grey')
    CARRIAGE_SIZE_PX=100

    carriage_display_containers = st.columns(
        spec=len(carriage_details),
        vertical_alignment='center',
        border=False,
    )

    for i in range(len(carriage_display_containers)):
        container = carriage_display_containers[i]
        with container:
            carriage = carriage_details[i+1]
            st_carriage_metric(
                carriage['label'],
                carriage['occupancy_percentage'], 
                carriage['occupancy_status']
            )

    # Occupancy status color legend
    st.markdown('<h3>Legend</h3>', unsafe_allow_html=True)
    for occupancy_status, color in OCCUPANCY_STATUS_COLORS.items():
        st.markdown(
            f"""
                <span style="display:flex; flex-direction:row; align-items:center;">
                    <span style="color:{color}; font-size:40px; -webkit-text-stroke: 2px black;">◼︎</span>
                    {occupancy_status.replace('_', ' ').capitalize()}
                </span>
            """,
            unsafe_allow_html=True
        )

def format_date(date: datetime.datetime) -> str:
    # Processing each piece separately so separate
    # attention can be given to the hour (to strip its leading 0s)
    month = date.strftime("%B")
    day = date.strftime("%d").lstrip('0')
    hour = date.strftime("%I").lstrip('0')
    minute = date.strftime("%M")
    am_pm = date.strftime("%p")
    return f"{month} {day}, {hour}:{minute} {am_pm}"

st.divider()

st.header('Alerts Monitor')
alerts = get_alerts()
alerts_list, alerts_metrics = st.columns(2)
# List of recent alerts
with alerts_list:
    with st.container(border=True, height=600):
        for alert in alerts:
            with st.container(border=True):
                alert_info, alert_severity = st.columns(2, vertical_alignment='center')
                with alert_info:
                    st.text(format_date(alert['created_at']))
                    st.markdown(f"[{alert['service_effect']}]({alert['url']})")
                    st.caption(alert['short_header'])
                with alert_severity:
                    st.metric(label='Severity', value=alert['severity'], help='"How severe the alert is from least (0) to most (10) severe."')
# Overall metrics about recent alerts
with alerts_metrics:

    alert_severities = [int(alert['severity']) for alert in alerts]
    
    avg_severity_widget, max_severity_widget, num_above_5_widget = st.columns(3)
    with avg_severity_widget:
        avg_severity = sum(alert_severities) / len(alerts)
        st.metric(value=avg_severity, label='Average Severity', border=True)
    with max_severity_widget:
        max_severity = max(alert_severities)
        st.metric(value=max_severity, label='Highest Severity', border=True)
    with num_above_5_widget:
        num_above_5 = len(list(filter(lambda severity: severity > 5, alert_severities)))
        st.metric(value=num_above_5, label='With Severity > 5', border=True)

    st.metric(value=len(alerts), label='Active Alerts', border=True)

##############################
# Active trips:
# |  A  |  B  | -C- |  D  |
#
# Trip C2100
# Current Status: In transit to Tufts Med.

# ...
# ^
# |            +---------------------------------------------------------------+
# |            | +---------+ +---------+ +---------+ +---------+ +---------+ +-|
# x Back Bay   | |  !91%   |-|    5%   |-|   23%   |-|  !100%  |-|    0%   |-| | =>
# |            | +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-+ 
# |            +---------------------------------------------------------------+
# |
# [[Prev. Stops]]
# |
# |            +---------------------------------------------------------------+
# |            | +---------+ +---------+ +---------+ +---------+ +---------+ +-|
# o Mass Ave   | |   25%   |-|    7%   |-|   23%   |-|   27%   |-|    0%   |-| | =>
# |            | +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-+ 
# |            +---------------------------------------------------------------+
# |
# |            +---------------------------------------------------------------+
# |            | +---------+ +---------+ +---------+ +---------+ +---------+ +-|
# o Ruggles    | |    0%   )-|   15%   )-|   23%   )-|  !56%   )-|    0%   )-| | =>
# |            | +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-+ 
# |            +---------------------------------------------------------------+
# |
# |            +---------------------------------------------------------------+
# |            | +---------+ +---------+ +---------+ +---------+ +---------+ +-|
# o RoxburyX   | |   11%   )-|    5%   )-|   23%   )-|    3%   )-|    0%   )-| | =>
# |            | +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-ooo-ooo-+ +-+ 
# |            +---------------------------------------------------------------+
# ...
