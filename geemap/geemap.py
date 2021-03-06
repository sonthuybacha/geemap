"""Main module for interactive mapping using Google Earth Engine Python API and ipyleaflet.
Keep in mind that Earth Engine functions use both camel case and snake case, such as setOptions(), setCenter(), centerObject(), addLayer().
ipyleaflet functions use snake case, such as add_tile_layer(), add_wms_layer(), add_minimap().
"""

import math
import os
import time
import ee
import ipyleaflet
import ipywidgets as widgets
from bqplot import pyplot as plt
from ipyfilechooser import FileChooser
from ipyleaflet import *
from IPython.display import display
from .basemaps import ee_basemaps
from .common import *
from .conversion import *
from .legends import builtin_legends


class Map(ipyleaflet.Map):
    """The Map class inherits from ipyleaflet.Map. The arguments you can pass to the Map can be found at https://ipyleaflet.readthedocs.io/en/latest/api_reference/map.html. By default, the Map will add Google Maps as the basemap. Set add_google_map = False to use OpenStreetMap as the basemap.

    Returns:
        object: ipyleaflet map object.
    """

    def __init__(self, **kwargs):

        # Authenticates Earth Engine and initializes an Earth Engine session
        if "ee_initialize" not in kwargs.keys():
            kwargs["ee_initialize"] = True

        if kwargs["ee_initialize"]:
            ee_initialize()

        # Default map center location and zoom level
        latlon = [40, -100]
        zoom = 4

        # Interchangeable parameters between ipyleaflet and folium

        if "height" not in kwargs.keys():
            kwargs["height"] = "550px"
        if "location" in kwargs.keys():
            kwargs["center"] = kwargs["location"]
            kwargs.pop("location")
        if "center" in kwargs.keys():
            latlon = kwargs["center"]
        else:
            kwargs["center"] = latlon

        if "zoom_start" in kwargs.keys():
            kwargs["zoom"] = kwargs["zoom_start"]
            kwargs.pop("zoom_start")
        if "zoom" in kwargs.keys():
            zoom = kwargs["zoom"]
        else:
            kwargs["zoom"] = zoom

        if "add_google_map" not in kwargs.keys():
            kwargs["add_google_map"] = True
        if "scroll_wheel_zoom" not in kwargs.keys():
            kwargs["scroll_wheel_zoom"] = True

        if "lite_mode" not in kwargs.keys():
            kwargs["lite_mode"] = False

        if kwargs["lite_mode"]:
            kwargs["data_ctrl"] = False
            kwargs["zoom_ctrl"] = True
            kwargs["fullscreen_ctrl"] = False
            kwargs["draw_ctrl"] = False
            kwargs["search_ctrl"] = False
            kwargs["measure_ctrl"] = False
            kwargs["scale_ctrl"] = False
            kwargs["layer_ctrl"] = False
            kwargs["inspector_ctrl"] = False
            kwargs["toolbar_ctrl"] = False
            kwargs["attribution_ctrl"] = False

        if "data_ctrl" not in kwargs.keys():
            kwargs["data_ctrl"] = True
        if "zoom_ctrl" not in kwargs.keys():
            kwargs["zoom_ctrl"] = True
        if "fullscreen_ctrl" not in kwargs.keys():
            kwargs["fullscreen_ctrl"] = True
        if "draw_ctrl" not in kwargs.keys():
            kwargs["draw_ctrl"] = True
        if "search_ctrl" not in kwargs.keys():
            kwargs["search_ctrl"] = True
        if "measure_ctrl" not in kwargs.keys():
            kwargs["measure_ctrl"] = True
        if "scale_ctrl" not in kwargs.keys():
            kwargs["scale_ctrl"] = True
        if "layer_ctrl" not in kwargs.keys():
            kwargs["layer_ctrl"] = True
        if "inspector_ctrl" not in kwargs.keys():
            kwargs["inspector_ctrl"] = True
        if "toolbar_ctrl" not in kwargs.keys():
            kwargs["toolbar_ctrl"] = False
        if "attribution_ctrl" not in kwargs.keys():
            kwargs["attribution_ctrl"] = True

        # Inherits the ipyleaflet Map class
        super().__init__(**kwargs)
        self.layout.height = kwargs["height"]

        self.clear_controls()

        self.draw_count = (
            0  # The number of shapes drawn by the user using the DrawControl
        )
        # The list of Earth Engine Geometry objects converted from geojson
        self.draw_features = []
        # The Earth Engine Geometry object converted from the last drawn feature
        self.draw_last_feature = None
        self.draw_layer = None
        self.draw_last_json = None
        self.draw_last_bounds = None
        self.user_roi = None
        self.user_rois = None

        self.roi_start = False
        self.roi_end = False
        self.roi_reducer = ee.Reducer.mean()
        self.roi_reducer_scale = None

        # List for storing pixel values and locations based on user-drawn geometries.
        self.chart_points = []
        self.chart_values = []
        self.chart_labels = None

        self.plot_widget = None  # The plot widget for plotting Earth Engine data
        self.plot_control = None  # The plot control for interacting plotting
        self.random_marker = None

        self.legend_widget = None
        self.legend_control = None

        self.ee_layers = []
        self.ee_layer_names = []
        self.ee_raster_layers = []
        self.ee_raster_layer_names = []
        self.ee_layer_dict = {}

        self.search_locations = None
        self.search_loc_marker = None
        self.search_loc_geom = None
        self.search_datasets = None
        self.screenshot = None
        self.toolbar = None
        self.toolbar_button = None

        # Adds search button and search box
        search_button = widgets.ToggleButton(
            value=False, tooltip="Search location/data", icon="globe"
        )
        search_button.layout.width = "36px"

        search_type = widgets.ToggleButtons(
            options=["name/address", "lat-lon", "data"],
            tooltips=[
                "Search by place name or address",
                "Search by lat-lon coordinates",
                "Search Earth Engine data catalog",
            ],
        )
        search_type.style.button_width = "110px"

        search_box = widgets.Text(
            placeholder="Search by place name or address",
            tooltip="Search location",
        )
        search_box.layout.width = "340px"

        search_output = widgets.Output(
            layout={"max_width": "340px", "max_height": "250px", "overflow": "scroll"}
        )

        search_results = widgets.RadioButtons()

        assets_dropdown = widgets.Dropdown()
        assets_dropdown.layout.min_width = "279px"
        assets_dropdown.layout.max_width = "279px"
        assets_dropdown.options = []

        import_btn = widgets.Button(
            description="import",
            button_style="primary",
            tooltip="Click to import the selected asset",
        )
        import_btn.layout.min_width = "57px"
        import_btn.layout.max_width = "57px"

        def import_btn_clicked(b):
            if assets_dropdown.value != "":
                datasets = self.search_datasets
                dataset = datasets[assets_dropdown.index]
                dataset_uid = "dataset_" + random_string(string_length=3)
                line1 = "{} = {}\n".format(dataset_uid, dataset["ee_id_snippet"])
                line2 = "Map.addLayer(" + dataset_uid + ', {}, "' + dataset["id"] + '")'
                contents = "".join([line1, line2])
                create_code_cell(contents)

        import_btn.on_click(import_btn_clicked)

        html_widget = widgets.HTML()

        def dropdown_change(change):
            dropdown_index = assets_dropdown.index
            if dropdown_index is not None and dropdown_index >= 0:
                with search_output:
                    search_output.clear_output(wait=True)
                    print("Loading ...")
                    datasets = self.search_datasets
                    dataset = datasets[dropdown_index]
                    dataset_html = ee_data_html(dataset)
                    html_widget.value = dataset_html
                    search_output.clear_output(wait=True)
                    display(html_widget)

        assets_dropdown.observe(dropdown_change, names="value")

        assets_combo = widgets.HBox()
        assets_combo.children = [import_btn, assets_dropdown]

        def search_result_change(change):
            result_index = search_results.index
            locations = self.search_locations
            location = locations[result_index]
            latlon = (location.lat, location.lng)
            self.search_loc_geom = ee.Geometry.Point(location.lng, location.lat)
            marker = self.search_loc_marker
            marker.location = latlon
            self.center = latlon

        search_results.observe(search_result_change, names="value")

        def search_btn_click(change):
            if change["new"]:
                search_widget.children = [search_button, search_result_widget]
            else:
                search_widget.children = [search_button]
                search_result_widget.children = [search_type, search_box]

        search_button.observe(search_btn_click, "value")

        def search_type_changed(change):
            search_box.value = ""
            search_output.clear_output()
            if change["new"] == "name/address":
                search_box.placeholder = "Search by place name or address, e.g., Paris"
                assets_dropdown.options = []
                search_result_widget.children = [search_type, search_box, search_output]
            elif change["new"] == "lat-lon":
                search_box.placeholder = "Search by lat-lon, e.g., 40, -100"
                assets_dropdown.options = []
                search_result_widget.children = [search_type, search_box, search_output]
            elif change["new"] == "data":
                search_box.placeholder = (
                    "Search GEE data catalog by keywords, e.g., elevation"
                )
                search_result_widget.children = [
                    search_type,
                    search_box,
                    assets_combo,
                    search_output,
                ]

        search_type.observe(search_type_changed, names="value")

        def search_box_callback(text):

            if text.value != "":

                if search_type.value == "name/address":
                    g = geocode(text.value)
                elif search_type.value == "lat-lon":
                    g = geocode(text.value, reverse=True)
                    if g is None and latlon_from_text(text.value):
                        search_output.clear_output()
                        latlon = latlon_from_text(text.value)
                        self.search_loc_geom = ee.Geometry.Point(latlon[1], latlon[0])
                        if self.search_loc_marker is None:
                            marker = Marker(
                                location=latlon, draggable=False, name="Search location"
                            )
                            self.search_loc_marker = marker
                            self.add_layer(marker)
                            self.center = latlon
                        else:
                            marker = self.search_loc_marker
                            marker.location = latlon
                            self.center = latlon
                        with search_output:
                            print("No address found for {}".format(latlon))
                        return
                elif search_type.value == "data":
                    search_output.clear_output()
                    with search_output:
                        print("Searching ...")
                    self.default_style = {"cursor": "wait"}
                    ee_assets = search_ee_data(text.value)
                    self.search_datasets = ee_assets
                    asset_titles = [x["title"] for x in ee_assets]
                    assets_dropdown.options = asset_titles
                    search_output.clear_output()
                    if len(ee_assets) > 0:
                        html_widget.value = ee_data_html(ee_assets[0])
                    with search_output:
                        display(html_widget)

                    self.default_style = {"cursor": "default"}

                    return

                self.search_locations = g
                if g is not None and len(g) > 0:
                    top_loc = g[0]
                    latlon = (top_loc.lat, top_loc.lng)
                    self.search_loc_geom = ee.Geometry.Point(top_loc.lng, top_loc.lat)
                    if self.search_loc_marker is None:
                        marker = Marker(
                            location=latlon, draggable=False, name="Search location"
                        )
                        self.search_loc_marker = marker
                        self.add_layer(marker)
                        self.center = latlon
                    else:
                        marker = self.search_loc_marker
                        marker.location = latlon
                        self.center = latlon
                    search_results.options = [x.address for x in g]
                    search_result_widget.children = [
                        search_type,
                        search_box,
                        search_output,
                    ]
                    with search_output:
                        search_output.clear_output(wait=True)
                        display(search_results)
                else:
                    with search_output:
                        search_output.clear_output()
                        print("No results could be found.")

        search_box.on_submit(search_box_callback)

        search_result_widget = widgets.VBox()
        search_result_widget.children = [search_type, search_box]

        search_widget = widgets.HBox()
        search_widget.children = [search_button]
        data_control = WidgetControl(widget=search_widget, position="topleft")

        if kwargs.get("data_ctrl"):
            self.add_control(control=data_control)

        search_marker = Marker(
            icon=AwesomeIcon(name="check", marker_color="green", icon_color="darkgreen")
        )
        search = SearchControl(
            position="topleft",
            url="https://nominatim.openstreetmap.org/search?format=json&q={s}",
            zoom=5,
            property_name="display_name",
            marker=search_marker,
        )
        if kwargs.get("search_ctrl"):
            self.add_control(search)

        if kwargs.get("zoom_ctrl"):
            self.add_control(ZoomControl(position="topleft"))

        if kwargs.get("layer_ctrl"):
            layer_control = LayersControl(position="topright")
            self.layer_control = layer_control
            self.add_control(layer_control)

        if kwargs.get("scale_ctrl"):
            scale = ScaleControl(position="bottomleft")
            self.scale_control = scale
            self.add_control(scale)

        if kwargs.get("fullscreen_ctrl"):
            fullscreen = FullScreenControl()
            self.fullscreen_control = fullscreen
            self.add_control(fullscreen)

        if kwargs.get("measure_ctrl"):
            measure = MeasureControl(
                position="bottomleft",
                active_color="orange",
                primary_length_unit="kilometers",
            )
            self.measure_control = measure
            self.add_control(measure)

        if kwargs.get("add_google_map"):
            self.add_layer(ee_basemaps["ROADMAP"])

        if kwargs.get("attribution_ctrl"):
            self.add_control(AttributionControl(position="bottomright"))

        draw_control = DrawControl(
            marker={"shapeOptions": {"color": "#0000FF"}},
            rectangle={"shapeOptions": {"color": "#0000FF"}},
            circle={"shapeOptions": {"color": "#0000FF"}},
            circlemarker={},
            edit=False,
            remove=False,
        )

        draw_control_lite = DrawControl(
            marker={},
            rectangle={"shapeOptions": {"color": "#0000FF"}},
            circle={"shapeOptions": {"color": "#0000FF"}},
            circlemarker={},
            polyline={},
            polygon={},
            edit=False,
            remove=False,
        )
        # Handles draw events

        def handle_draw(target, action, geo_json):
            try:
                # print(geo_json)
                # geo_json = adjust_longitude(geo_json)
                # print(geo_json)
                self.roi_start = True
                self.draw_count += 1
                geom = geojson_to_ee(geo_json, False)
                self.user_roi = geom
                feature = ee.Feature(geom)
                self.draw_last_json = geo_json
                # self.draw_last_bounds = minimum_bounding_box(geo_json)
                self.draw_last_feature = feature
                self.draw_features.append(feature)
                collection = ee.FeatureCollection(self.draw_features)
                self.user_rois = collection
                ee_draw_layer = ee_tile_layer(
                    collection, {"color": "blue"}, "Drawn Features", True, 0.5
                )
                if self.draw_count == 1:
                    self.add_layer(ee_draw_layer)
                    self.draw_layer = ee_draw_layer
                else:
                    self.substitute_layer(self.draw_layer, ee_draw_layer)
                    self.draw_layer = ee_draw_layer

                draw_control.clear()

                self.roi_end = True
                self.roi_start = False
            except Exception as e:
                print(e)
                print("There was an error creating Earth Engine Feature.")
                self.draw_count = 0
                self.draw_features = []
                self.draw_last_feature = None
                self.draw_layer = None
                self.user_roi = None
                self.roi_start = False
                self.roi_end = False

        draw_control.on_draw(handle_draw)
        if kwargs.get("draw_ctrl"):
            self.add_control(draw_control)
        self.draw_control = draw_control
        self.draw_control_lite = draw_control_lite

        # Dropdown widget for plotting
        self.plot_dropdown_control = None
        self.plot_dropdown_widget = None
        self.plot_options = {}

        self.plot_marker_cluster = MarkerCluster(name="Marker Cluster")
        self.plot_coordinates = []
        self.plot_markers = []
        self.plot_last_click = []
        self.plot_all_clicks = []

        # Adds Inspector widget
        inspector_checkbox = widgets.Checkbox(
            value=False,
            description="Inspector",
            indent=False,
            layout=widgets.Layout(height="18px"),
        )
        inspector_checkbox.layout.width = "13ex"

        # Adds Plot widget
        plot_checkbox = widgets.Checkbox(
            value=False,
            description="Plotting",
            indent=False,
        )
        plot_checkbox.layout.width = "13ex"
        self.plot_checkbox = plot_checkbox

        vb = widgets.VBox(children=[inspector_checkbox, plot_checkbox])

        chk_control = WidgetControl(widget=vb, position="topright")
        if kwargs.get("inspector_ctrl"):
            self.add_control(chk_control)
        self.inspector_control = chk_control

        self.inspector_checked = inspector_checkbox.value
        self.plot_checked = plot_checkbox.value

        def inspect_chk_changed(b):
            self.inspector_checked = inspector_checkbox.value
            if not self.inspector_checked:
                output.clear_output()

        inspector_checkbox.observe(inspect_chk_changed)

        output = widgets.Output(layout={"border": "1px solid black"})
        output_control = WidgetControl(widget=output, position="topright")
        self.add_control(output_control)

        def plot_chk_changed(button):

            if button["name"] == "value" and button["new"]:
                self.plot_checked = True
                plot_dropdown_widget = widgets.Dropdown(
                    options=list(self.ee_raster_layer_names),
                )
                plot_dropdown_widget.layout.width = "18ex"
                self.plot_dropdown_widget = plot_dropdown_widget
                plot_dropdown_control = WidgetControl(
                    widget=plot_dropdown_widget, position="topright"
                )
                self.plot_dropdown_control = plot_dropdown_control
                self.add_control(plot_dropdown_control)
                self.remove_control(self.draw_control)
                self.add_control(self.draw_control_lite)
            elif button["name"] == "value" and (not button["new"]):
                self.plot_checked = False
                plot_dropdown_widget = self.plot_dropdown_widget
                plot_dropdown_control = self.plot_dropdown_control
                self.remove_control(plot_dropdown_control)
                del plot_dropdown_widget
                del plot_dropdown_control
                if self.plot_control in self.controls:
                    plot_control = self.plot_control
                    plot_widget = self.plot_widget
                    self.remove_control(plot_control)
                    self.plot_control = None
                    self.plot_widget = None
                    del plot_control
                    del plot_widget
                if (
                    self.plot_marker_cluster is not None
                    and self.plot_marker_cluster in self.layers
                ):
                    self.remove_layer(self.plot_marker_cluster)
                self.remove_control(self.draw_control_lite)
                self.add_control(self.draw_control)

        plot_checkbox.observe(plot_chk_changed)

        tool_output = widgets.Output()
        tool_output.clear_output(wait=True)

        save_map_widget = widgets.VBox()

        save_type = widgets.ToggleButtons(
            options=["HTML", "PNG", "JPG"],
            tooltips=[
                "Save the map as an HTML file",
                "Take a screenshot and save as a PNG file",
                "Take a screenshot and save as a JPG file",
            ],
        )

        # download_dir = os.getcwd()
        file_chooser = FileChooser(os.getcwd())
        file_chooser.default_filename = "my_map.html"
        file_chooser.use_dir_icons = False

        ok_cancel = widgets.ToggleButtons(
            options=["OK", "Cancel"], tooltips=["OK", "Cancel"], button_style="primary"
        )
        ok_cancel.value = None

        def save_type_changed(change):
            ok_cancel.value = None
            # file_chooser.reset()
            file_chooser.default_path = os.getcwd()
            if change["new"] == "HTML":
                file_chooser.default_filename = "my_map.html"
            elif change["new"] == "PNG":
                file_chooser.default_filename = "my_map.png"
            elif change["new"] == "JPG":
                file_chooser.default_filename = "my_map.jpg"
            save_map_widget.children = [save_type, file_chooser]

        def chooser_callback(chooser):
            # file_chooser.default_path = os.getcwd()
            save_map_widget.children = [save_type, file_chooser, ok_cancel]

        def ok_cancel_clicked(change):
            if change["new"] == "OK":
                file_path = file_chooser.selected
                ext = os.path.splitext(file_path)[1]
                if save_type.value == "HTML" and ext.upper() == ".HTML":
                    tool_output.clear_output()
                    self.to_html(file_path)
                elif save_type.value == "PNG" and ext.upper() == ".PNG":
                    tool_output.clear_output()
                    self.toolbar_button.value = False
                    time.sleep(1)
                    screen_capture(outfile=file_path)
                elif save_type.value == "JPG" and ext.upper() == ".JPG":
                    tool_output.clear_output()
                    self.toolbar_button.value = False
                    time.sleep(1)
                    screen_capture(outfile=file_path)
                else:
                    label = widgets.Label(
                        value="The selected file extension does not match the selected exporting type."
                    )
                    save_map_widget.children = [save_type, file_chooser, label]
                self.toolbar_reset()
            elif change["new"] == "Cancel":
                tool_output.clear_output()
                self.toolbar_reset()

        save_type.observe(save_type_changed, names="value")
        ok_cancel.observe(ok_cancel_clicked, names="value")

        file_chooser.register_callback(chooser_callback)

        save_map_widget.children = [save_type, file_chooser]

        tools = {
            "mouse-pointer": "pointer",
            "camera": "to_image",
            "info": "identify",
            "map-marker": "plotting",
        }
        icons = ["mouse-pointer", "camera", "info", "map-marker"]
        tooltips = [
            "Default pointer",
            "Save map as HTML or image",
            "Inspector",
            "Plotting",
        ]
        icon_width = "42px"
        icon_height = "40px"
        n_cols = 2
        n_rows = math.ceil(len(icons) / n_cols)

        toolbar_grid = widgets.GridBox(
            children=[
                widgets.ToggleButton(
                    layout=widgets.Layout(width="auto", height="auto"),
                    button_style="primary",
                    icon=icons[i],
                    tooltip=tooltips[i],
                )
                for i in range(len(icons))
            ],
            layout=widgets.Layout(
                width="90px",
                grid_template_columns=(icon_width + " ") * 2,
                grid_template_rows=(icon_height + " ") * n_rows,
                grid_gap="1px 1px",
            ),
        )
        self.toolbar = toolbar_grid

        def tool_callback(change):
            if change["new"]:
                current_tool = change["owner"]
                for tool in toolbar_grid.children:
                    if not tool is current_tool:
                        tool.value = False
                tool = change["owner"]
                if tools[tool.icon] == "to_image":
                    with tool_output:
                        tool_output.clear_output()
                        display(save_map_widget)
            else:
                tool_output.clear_output()
                save_map_widget.children = [save_type, file_chooser]

        for tool in toolbar_grid.children:
            tool.observe(tool_callback, "value")

        toolbar_button = widgets.ToggleButton(
            value=False, tooltip="Toolbar", icon="wrench"
        )
        toolbar_button.layout.width = "37px"
        self.toolbar_button = toolbar_button

        def toolbar_btn_click(change):
            if change["new"]:
                toolbar_widget.children = [toolbar_button, toolbar_grid]
            else:
                toolbar_widget.children = [toolbar_button]
                tool_output.clear_output()
                self.toolbar_reset()

        toolbar_button.observe(toolbar_btn_click, "value")

        toolbar_widget = widgets.VBox()
        toolbar_widget.children = [toolbar_button]
        toolbar_control = WidgetControl(widget=toolbar_widget, position="topright")
        if kwargs.get("toolbar_ctrl"):
            self.add_control(toolbar_control)

        tool_output_control = WidgetControl(widget=tool_output, position="topright")
        self.add_control(tool_output_control)

        def handle_interaction(**kwargs):
            latlon = kwargs.get("coordinates")
            if kwargs.get("type") == "click" and self.inspector_checked:
                self.default_style = {"cursor": "wait"}

                sample_scale = self.getScale()
                layers = self.ee_layers

                with output:

                    output.clear_output(wait=True)
                    for index, ee_object in enumerate(layers):
                        xy = ee.Geometry.Point(latlon[::-1])
                        layer_names = self.ee_layer_names
                        layer_name = layer_names[index]
                        object_type = ee_object.__class__.__name__

                        try:
                            if isinstance(ee_object, ee.ImageCollection):
                                ee_object = ee_object.mosaic()
                            elif (
                                isinstance(ee_object, ee.geometry.Geometry)
                                or isinstance(ee_object, ee.feature.Feature)
                                or isinstance(
                                    ee_object, ee.featurecollection.FeatureCollection
                                )
                            ):
                                ee_object = ee.FeatureCollection(ee_object)

                            if isinstance(ee_object, ee.Image):
                                item = ee_object.reduceRegion(
                                    ee.Reducer.first(), xy, sample_scale
                                ).getInfo()
                                b_name = "band"
                                if len(item) > 1:
                                    b_name = "bands"
                                print(
                                    "{}: {} ({} {})".format(
                                        layer_name, object_type, len(item), b_name
                                    )
                                )
                                keys = item.keys()
                                for key in keys:
                                    print("  {}: {}".format(key, item[key]))
                            elif isinstance(ee_object, ee.FeatureCollection):
                                filtered = ee_object.filterBounds(xy)
                                size = filtered.size().getInfo()
                                if size > 0:
                                    first = filtered.first()
                                    props = first.toDictionary().getInfo()
                                    b_name = "property"
                                    if len(props) > 1:
                                        b_name = "properties"
                                    print(
                                        "{}: Feature ({} {})".format(
                                            layer_name, len(props), b_name
                                        )
                                    )
                                    keys = props.keys()
                                    for key in keys:
                                        print("  {}: {}".format(key, props[key]))
                        except Exception as e:
                            print(e)

                self.default_style = {"cursor": "crosshair"}
            if (
                kwargs.get("type") == "click"
                and self.plot_checked
                and len(self.ee_raster_layers) > 0
            ):
                plot_layer_name = self.plot_dropdown_widget.value
                layer_names = self.ee_raster_layer_names
                layers = self.ee_raster_layers
                index = layer_names.index(plot_layer_name)
                ee_object = layers[index]

                if isinstance(ee_object, ee.ImageCollection):
                    ee_object = ee_object.mosaic()

                try:
                    self.default_style = {"cursor": "wait"}
                    plot_options = self.plot_options
                    sample_scale = self.getScale()
                    if "sample_scale" in plot_options.keys() and (
                        plot_options["sample_scale"] is not None
                    ):
                        sample_scale = plot_options["sample_scale"]
                    if "title" not in plot_options.keys():
                        plot_options["title"] = plot_layer_name
                    if ("add_marker_cluster" in plot_options.keys()) and plot_options[
                        "add_marker_cluster"
                    ]:
                        plot_coordinates = self.plot_coordinates
                        markers = self.plot_markers
                        marker_cluster = self.plot_marker_cluster
                        plot_coordinates.append(latlon)
                        self.plot_last_click = latlon
                        self.plot_all_clicks = plot_coordinates
                        markers.append(Marker(location=latlon))
                        marker_cluster.markers = markers
                        self.plot_marker_cluster = marker_cluster

                    band_names = ee_object.bandNames().getInfo()
                    self.chart_labels = band_names

                    if self.roi_end:
                        if self.roi_reducer_scale is None:
                            scale = ee_object.select(0).projection().nominalScale()
                        else:
                            scale = self.roi_reducer_scale
                        dict_values = ee_object.reduceRegion(
                            reducer=self.roi_reducer,
                            geometry=self.user_roi,
                            scale=scale,
                            bestEffort=True,
                        ).getInfo()
                        self.chart_points.append(
                            self.user_roi.centroid(1).coordinates().getInfo()
                        )
                    else:
                        xy = ee.Geometry.Point(latlon[::-1])
                        dict_values = (
                            ee_object.sample(xy, scale=sample_scale)
                            .first()
                            .toDictionary()
                            .getInfo()
                        )
                        self.chart_points.append(xy.coordinates().getInfo())
                    band_values = list(dict_values.values())
                    self.chart_values.append(band_values)
                    self.plot(band_names, band_values, **plot_options)
                    if plot_options["title"] == plot_layer_name:
                        del plot_options["title"]
                    self.default_style = {"cursor": "crosshair"}
                    self.roi_end = False
                except Exception as e:
                    if self.plot_widget is not None:
                        with self.plot_widget:
                            self.plot_widget.clear_output()
                            print("No data for the clicked location.")
                    else:
                        print(e)
                    self.default_style = {"cursor": "crosshair"}
                    self.roi_end = False

        self.on_interaction(handle_interaction)

    def set_options(self, mapTypeId="HYBRID", styles=None, types=None):
        """Adds Google basemap and controls to the ipyleaflet map.

        Args:
            mapTypeId (str, optional): A mapTypeId to set the basemap to. Can be one of "ROADMAP", "SATELLITE", "HYBRID" or "TERRAIN" to select one of the standard Google Maps API map types. Defaults to 'HYBRID'.
            styles (object, optional): A dictionary of custom MapTypeStyle objects keyed with a name that will appear in the map's Map Type Controls. Defaults to None.
            types (list, optional): A list of mapTypeIds to make available. If omitted, but opt_styles is specified, appends all of the style keys to the standard Google Maps API map types.. Defaults to None.
        """
        self.clear_layers()
        self.clear_controls()
        self.scroll_wheel_zoom = True
        self.add_control(ZoomControl(position="topleft"))
        self.add_control(LayersControl(position="topright"))
        self.add_control(ScaleControl(position="bottomleft"))
        self.add_control(FullScreenControl())
        self.add_control(DrawControl())

        measure = MeasureControl(
            position="bottomleft",
            active_color="orange",
            primary_length_unit="kilometers",
        )
        self.add_control(measure)

        try:
            self.add_layer(ee_basemaps[mapTypeId])
        except Exception as e:
            print(e)
            print(
                'Google basemaps can only be one of "ROADMAP", "SATELLITE", "HYBRID" or "TERRAIN".'
            )

    setOptions = set_options

    def add_ee_layer(
        self, ee_object, vis_params={}, name=None, shown=True, opacity=1.0
    ):
        """Adds a given EE object to the map as a layer.

        Args:
            ee_object (Collection|Feature|Image|MapId): The object to add to the map.
            vis_params (dict, optional): The visualization parameters. Defaults to {}.
            name (str, optional): The name of the layer. Defaults to 'Layer N'.
            shown (bool, optional): A flag indicating whether the layer should be on by default. Defaults to True.
            opacity (float, optional): The layer's opacity represented as a number between 0 and 1. Defaults to 1.
        """
        image = None
        if name is None:
            layer_count = len(self.layers)
            name = "Layer " + str(layer_count + 1)

        if (
            not isinstance(ee_object, ee.Image)
            and not isinstance(ee_object, ee.ImageCollection)
            and not isinstance(ee_object, ee.FeatureCollection)
            and not isinstance(ee_object, ee.Feature)
            and not isinstance(ee_object, ee.Geometry)
        ):
            err_str = "\n\nThe image argument in 'addLayer' function must be an instace of one of ee.Image, ee.Geometry, ee.Feature or ee.FeatureCollection."
            raise AttributeError(err_str)

        if (
            isinstance(ee_object, ee.geometry.Geometry)
            or isinstance(ee_object, ee.feature.Feature)
            or isinstance(ee_object, ee.featurecollection.FeatureCollection)
        ):
            features = ee.FeatureCollection(ee_object)

            width = 2

            if "width" in vis_params:
                width = vis_params["width"]

            color = "000000"

            if "color" in vis_params:
                color = vis_params["color"]

            image_fill = features.style(**{"fillColor": color}).updateMask(
                ee.Image.constant(0.5)
            )
            image_outline = features.style(
                **{"color": color, "fillColor": "00000000", "width": width}
            )

            image = image_fill.blend(image_outline)
        elif isinstance(ee_object, ee.image.Image):
            image = ee_object
        elif isinstance(ee_object, ee.imagecollection.ImageCollection):
            image = ee_object.mosaic()

        map_id_dict = ee.Image(image).getMapId(vis_params)
        tile_layer = ipyleaflet.TileLayer(
            url=map_id_dict["tile_fetcher"].url_format,
            attribution="Google Earth Engine",
            name=name,
            opacity=opacity,
            visible=True
            # visible=shown
        )

        layer = self.find_layer(name=name)
        if layer is not None:

            existing_object = self.ee_layer_dict[name]["ee_object"]

            if isinstance(existing_object, ee.Image) or isinstance(
                existing_object, ee.ImageCollection
            ):
                self.ee_raster_layers.remove(existing_object)
                self.ee_raster_layer_names.remove(name)
                if self.plot_dropdown_widget is not None:
                    self.plot_dropdown_widget.options = list(self.ee_raster_layer_names)

            self.ee_layers.remove(existing_object)
            self.ee_layer_names.remove(name)
            self.remove_layer(layer)

        self.ee_layers.append(ee_object)
        self.ee_layer_names.append(name)
        self.ee_layer_dict[name] = {"ee_object": ee_object, "ee_layer": tile_layer}

        self.add_layer(tile_layer)

        if isinstance(ee_object, ee.Image) or isinstance(ee_object, ee.ImageCollection):
            self.ee_raster_layers.append(ee_object)
            self.ee_raster_layer_names.append(name)
            if self.plot_dropdown_widget is not None:
                self.plot_dropdown_widget.options = list(self.ee_raster_layer_names)

    addLayer = add_ee_layer

    def set_center(self, lon, lat, zoom=None):
        """Centers the map view at a given coordinates with the given zoom level.

        Args:
            lon (float): The longitude of the center, in degrees.
            lat (float): The latitude of the center, in degrees.
            zoom (int, optional): The zoom level, from 1 to 24. Defaults to None.
        """
        self.center = (lat, lon)
        if zoom is not None:
            self.zoom = zoom

    setCenter = set_center

    def center_object(self, ee_object, zoom=None):
        """Centers the map view on a given object.

        Args:
            ee_object (Element|Geometry): An Earth Engine object to center on - a geometry, image or feature.
            zoom (int, optional): The zoom level, from 1 to 24. Defaults to None.
        """
        lat = 0
        lon = 0
        bounds = [[lat, lon], [lat, lon]]
        if isinstance(ee_object, ee.geometry.Geometry):
            centroid = ee_object.centroid(1)
            lon, lat = centroid.getInfo()["coordinates"]
            bounds = [[lat, lon], [lat, lon]]
        elif isinstance(ee_object, ee.feature.Feature):
            centroid = ee_object.geometry().centroid(1)
            lon, lat = centroid.getInfo()["coordinates"]
            bounds = [[lat, lon], [lat, lon]]
        elif isinstance(ee_object, ee.featurecollection.FeatureCollection):
            centroid = ee_object.geometry().centroid()
            lon, lat = centroid.getInfo()["coordinates"]
            bounds = [[lat, lon], [lat, lon]]
        elif isinstance(ee_object, ee.image.Image):
            geometry = ee_object.geometry()
            coordinates = geometry.getInfo()["coordinates"][0]
            bounds = [coordinates[0][::-1], coordinates[2][::-1]]
        elif isinstance(ee_object, ee.imagecollection.ImageCollection):
            geometry = ee_object.geometry()
            coordinates = geometry.getInfo()["coordinates"][0]
            bounds = [coordinates[0][::-1], coordinates[2][::-1]]
        else:
            bounds = [[0, 0], [0, 0]]

        lat = bounds[0][0]
        lon = bounds[0][1]

        self.setCenter(lon, lat, zoom)

    centerObject = center_object

    def get_scale(self):
        """Returns the approximate pixel scale of the current map view, in meters.

        Returns:
            float: Map resolution in meters.
        """
        zoom_level = self.zoom
        # Reference: https://blogs.bing.com/maps/2006/02/25/map-control-zoom-levels-gt-resolution
        resolution = 156543.04 * math.cos(0) / math.pow(2, zoom_level)
        return resolution

    getScale = get_scale

    def add_basemap(self, basemap="HYBRID"):
        """Adds a basemap to the map.

        Args:
            basemap (str, optional): Can be one of string from ee_basemaps. Defaults to 'HYBRID'.
        """
        try:
            self.add_layer(ee_basemaps[basemap])
        except Exception as e:
            print(e)
            print(
                "Basemap can only be one of the following:\n  {}".format(
                    "\n  ".join(ee_basemaps.keys())
                )
            )

    def find_layer(self, name):
        """Finds layer by name

        Args:
            name (str): Name of the layer to find.

        Returns:
            object: ipyleaflet layer object.
        """
        layers = self.layers

        for layer in layers:
            if layer.name == name:
                return layer

        return None

    def layer_opacity(self, name, value=1.0):
        """Changes layer opacity.

        Args:
            name (str): The name of the layer to change opacity.
            value (float, optional): The opacity value to set. Defaults to 1.0.
        """
        layer = self.find_layer(name)
        try:
            layer.opacity = value
            # layer.interact(opacity=(0, 1, 0.1))  # to change layer opacity interactively
        except Exception as e:
            print(e)

    def add_wms_layer(
        self,
        url,
        layers,
        name=None,
        attribution="",
        format="image/jpeg",
        transparent=False,
        opacity=1.0,
        shown=True,
    ):
        """Add a WMS layer to the map.

        Args:
            url (str): The URL of the WMS web service.
            layers (str): Comma-separated list of WMS layers to show.
            name (str, optional): The layer name to use on the layer control. Defaults to None.
            attribution (str, optional): The attribution of the data layer. Defaults to ''.
            format (str, optional): WMS image format (use ‘image/png’ for layers with transparency). Defaults to 'image/jpeg'.
            transparent (bool, optional): If True, the WMS service will return images with transparency. Defaults to False.
            opacity (float, optional): The opacity of the layer. Defaults to 1.0.
            shown (bool, optional): A flag indicating whether the layer should be on by default. Defaults to True.
        """

        if name is None:
            name = str(layers)

        try:
            wms_layer = ipyleaflet.WMSLayer(
                url=url,
                layers=layers,
                name=name,
                attribution=attribution,
                format=format,
                transparent=transparent,
                opacity=opacity,
                visible=True
                # visible=shown
            )
            self.add_layer(wms_layer)
        except Exception as e:
            print(e)
            print("Failed to add the specified WMS TileLayer.")

    def add_tile_layer(
        self,
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        name=None,
        attribution="",
        opacity=1.0,
        shown=True,
    ):
        """Adds a TileLayer to the map.

        Args:
            url (str, optional): The URL of the tile layer. Defaults to 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'.
            name (str, optional): The layer name to use for the layer. Defaults to None.
            attribution (str, optional): The attribution to use. Defaults to ''.
            opacity (float, optional): The opacity of the layer. Defaults to 1.
            shown (bool, optional): A flag indicating whether the layer should be on by default. Defaults to True.
        """
        try:
            tile_layer = ipyleaflet.TileLayer(
                url=url,
                name=name,
                attribution=attribution,
                opacity=opacity,
                visible=True
                # visible=shown
            )
            self.add_layer(tile_layer)
        except Exception as e:
            print(e)
            print("Failed to add the specified TileLayer.")

    def add_minimap(self, zoom=5, position="bottomright"):
        """Adds a minimap (overview) to the ipyleaflet map.

        Args:
            zoom (int, optional): Initial map zoom level. Defaults to 5.
            position (str, optional): Position of the minimap. Defaults to "bottomright".
        """
        minimap = ipyleaflet.Map(
            zoom_control=False,
            attribution_control=False,
            zoom=5,
            center=self.center,
            layers=[ee_basemaps["ROADMAP"]],
        )
        minimap.layout.width = "150px"
        minimap.layout.height = "150px"
        link((minimap, "center"), (self, "center"))
        minimap_control = WidgetControl(widget=minimap, position=position)
        self.add_control(minimap_control)

    def marker_cluster(self):
        """Adds a marker cluster to the map and returns a list of ee.Feature, which can be accessed using Map.ee_marker_cluster.

        Returns:
            object: a list of ee.Feature
        """
        coordinates = []
        markers = []
        marker_cluster = MarkerCluster(name="Marker Cluster")
        self.last_click = []
        self.all_clicks = []
        self.ee_markers = []
        self.add_layer(marker_cluster)

        def handle_interaction(**kwargs):
            latlon = kwargs.get("coordinates")
            if kwargs.get("type") == "click":
                coordinates.append(latlon)
                geom = ee.Geometry.Point(latlon[1], latlon[0])
                feature = ee.Feature(geom)
                self.ee_markers.append(feature)
                self.last_click = latlon
                self.all_clicks = coordinates
                markers.append(Marker(location=latlon))
                marker_cluster.markers = markers
            elif kwargs.get("type") == "mousemove":
                pass

        # cursor style: https://www.w3schools.com/cssref/pr_class_cursor.asp
        self.default_style = {"cursor": "crosshair"}
        self.on_interaction(handle_interaction)

    def set_plot_options(
        self,
        add_marker_cluster=False,
        sample_scale=None,
        plot_type=None,
        overlay=False,
        position="bottomright",
        min_width=None,
        max_width=None,
        min_height=None,
        max_height=None,
        **kwargs
    ):
        """Sets plotting options.

        Args:
            add_marker_cluster (bool, optional): Whether to add a marker cluster. Defaults to False.
            sample_scale (float, optional):  A nominal scale in meters of the projection to sample in . Defaults to None.
            plot_type (str, optional): The plot type can be one of "None", "bar", "scatter" or "hist". Defaults to None.
            overlay (bool, optional): Whether to overlay plotted lines on the figure. Defaults to False.
            position (str, optional): Position of the control, can be ‘bottomleft’, ‘bottomright’, ‘topleft’, or ‘topright’. Defaults to 'bottomright'.
            min_width (int, optional): Min width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_width (int, optional): Max width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            min_height (int, optional): Min height of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_height (int, optional): Max height of the widget (in pixels), if None it will respect the content size. Defaults to None.

        """
        plot_options_dict = {}
        plot_options_dict["add_marker_cluster"] = add_marker_cluster
        plot_options_dict["sample_scale"] = sample_scale
        plot_options_dict["plot_type"] = plot_type
        plot_options_dict["overlay"] = overlay
        plot_options_dict["position"] = position
        plot_options_dict["min_width"] = min_width
        plot_options_dict["max_width"] = max_width
        plot_options_dict["min_height"] = min_height
        plot_options_dict["max_height"] = max_height

        for key in kwargs.keys():
            plot_options_dict[key] = kwargs[key]

        self.plot_options = plot_options_dict

        if add_marker_cluster and (self.plot_marker_cluster not in self.layers):
            self.add_layer(self.plot_marker_cluster)

    def plot(
        self,
        x,
        y,
        plot_type=None,
        overlay=False,
        position="bottomright",
        min_width=None,
        max_width=None,
        min_height=None,
        max_height=None,
        **kwargs
    ):
        """Creates a plot based on x-array and y-array data.

        Args:
            x (numpy.ndarray or list): The x-coordinates of the plotted line.
            y (numpy.ndarray or list): The y-coordinates of the plotted line.
            plot_type (str, optional): The plot type can be one of "None", "bar", "scatter" or "hist". Defaults to None.
            overlay (bool, optional): Whether to overlay plotted lines on the figure. Defaults to False.
            position (str, optional): Position of the control, can be ‘bottomleft’, ‘bottomright’, ‘topleft’, or ‘topright’. Defaults to 'bottomright'.
            min_width (int, optional): Min width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_width (int, optional): Max width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            min_height (int, optional): Min height of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_height (int, optional): Max height of the widget (in pixels), if None it will respect the content size. Defaults to None.

        """
        if self.plot_widget is not None:
            plot_widget = self.plot_widget
        else:
            plot_widget = widgets.Output(layout={"border": "1px solid black"})
            plot_control = WidgetControl(
                widget=plot_widget,
                position=position,
                min_width=min_width,
                max_width=max_width,
                min_height=min_height,
                max_height=max_height,
            )
            self.plot_widget = plot_widget
            self.plot_control = plot_control
            self.add_control(plot_control)

        if max_width is None:
            max_width = 500
        if max_height is None:
            max_height = 300

        if (plot_type is None) and ("markers" not in kwargs.keys()):
            kwargs["markers"] = "circle"

        with plot_widget:
            try:
                fig = plt.figure(1, **kwargs)
                if max_width is not None:
                    fig.layout.width = str(max_width) + "px"
                if max_height is not None:
                    fig.layout.height = str(max_height) + "px"

                plot_widget.clear_output(wait=True)
                if not overlay:
                    plt.clear()

                if plot_type is None:
                    if "marker" not in kwargs.keys():
                        kwargs["marker"] = "circle"
                    plt.plot(x, y, **kwargs)
                elif plot_type == "bar":
                    plt.bar(x, y, **kwargs)
                elif plot_type == "scatter":
                    plt.scatter(x, y, **kwargs)
                elif plot_type == "hist":
                    plt.hist(y, **kwargs)
                plt.show()

            except Exception as e:
                print(e)
                print("Failed to create plot.")

    def plot_demo(
        self,
        iterations=20,
        plot_type=None,
        overlay=False,
        position="bottomright",
        min_width=None,
        max_width=None,
        min_height=None,
        max_height=None,
        **kwargs
    ):
        """A demo of interactive plotting using random pixel coordinates.

        Args:
            iterations (int, optional): How many iterations to run for the demo. Defaults to 20.
            plot_type (str, optional): The plot type can be one of "None", "bar", "scatter" or "hist". Defaults to None.
            overlay (bool, optional): Whether to overlay plotted lines on the figure. Defaults to False.
            position (str, optional): Position of the control, can be ‘bottomleft’, ‘bottomright’, ‘topleft’, or ‘topright’. Defaults to 'bottomright'.
            min_width (int, optional): Min width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_width (int, optional): Max width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            min_height (int, optional): Min height of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_height (int, optional): Max height of the widget (in pixels), if None it will respect the content size. Defaults to None.
        """

        import numpy as np
        import time

        if self.random_marker is not None:
            self.remove_layer(self.random_marker)

        image = ee.Image("LE7_TOA_5YEAR/1999_2003").select([0, 1, 2, 3, 4, 6])
        self.addLayer(
            image,
            {"bands": ["B4", "B3", "B2"], "gamma": 1.4},
            "LE7_TOA_5YEAR/1999_2003",
        )
        self.setCenter(-50.078877, 25.190030, 3)
        band_names = image.bandNames().getInfo()
        # band_count = len(band_names)

        latitudes = np.random.uniform(30, 48, size=iterations)
        longitudes = np.random.uniform(-121, -76, size=iterations)

        marker = Marker(location=(0, 0))
        self.random_marker = marker
        self.add_layer(marker)

        for i in range(iterations):
            try:
                coordinate = ee.Geometry.Point([longitudes[i], latitudes[i]])
                dict_values = image.sample(coordinate).first().toDictionary().getInfo()
                band_values = list(dict_values.values())
                title = "{}/{}: Spectral signature at ({}, {})".format(
                    i + 1, iterations, round(latitudes[i], 2), round(longitudes[i], 2)
                )
                marker.location = (latitudes[i], longitudes[i])
                self.plot(
                    band_names,
                    band_values,
                    plot_type=plot_type,
                    overlay=overlay,
                    min_width=min_width,
                    max_width=max_width,
                    min_height=min_height,
                    max_height=max_height,
                    title=title,
                    **kwargs
                )
                time.sleep(0.3)
            except Exception as e:
                print(e)

    def plot_raster(
        self,
        ee_object=None,
        sample_scale=None,
        plot_type=None,
        overlay=False,
        position="bottomright",
        min_width=None,
        max_width=None,
        min_height=None,
        max_height=None,
        **kwargs
    ):
        """Interactive plotting of Earth Engine data by clicking on the map.

        Args:
            ee_object (object, optional): The ee.Image or ee.ImageCollection to sample. Defaults to None.
            sample_scale (float, optional): A nominal scale in meters of the projection to sample in. Defaults to None.
            plot_type (str, optional): The plot type can be one of "None", "bar", "scatter" or "hist". Defaults to None.
            overlay (bool, optional): Whether to overlay plotted lines on the figure. Defaults to False.
            position (str, optional): Position of the control, can be ‘bottomleft’, ‘bottomright’, ‘topleft’, or ‘topright’. Defaults to 'bottomright'.
            min_width (int, optional): Min width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_width (int, optional): Max width of the widget (in pixels), if None it will respect the content size. Defaults to None.
            min_height (int, optional): Min height of the widget (in pixels), if None it will respect the content size. Defaults to None.
            max_height (int, optional): Max height of the widget (in pixels), if None it will respect the content size. Defaults to None.

        """
        if self.plot_control is not None:
            del self.plot_widget
            self.remove_control(self.plot_control)

        if self.random_marker is not None:
            self.remove_layer(self.random_marker)

        plot_widget = widgets.Output(layout={"border": "1px solid black"})
        plot_control = WidgetControl(
            widget=plot_widget,
            position=position,
            min_width=min_width,
            max_width=max_width,
            min_height=min_height,
            max_height=max_height,
        )
        self.plot_widget = plot_widget
        self.plot_control = plot_control
        self.add_control(plot_control)

        self.default_style = {"cursor": "crosshair"}
        msg = "The plot function can only be used on ee.Image or ee.ImageCollection with more than one band."
        if (ee_object is None) and len(self.ee_raster_layers) > 0:
            ee_object = self.ee_raster_layers[-1]
            if isinstance(ee_object, ee.ImageCollection):
                ee_object = ee_object.mosaic()
        elif isinstance(ee_object, ee.ImageCollection):
            ee_object = ee_object.mosaic()
        elif not isinstance(ee_object, ee.Image):
            print(msg)
            return

        if sample_scale is None:
            sample_scale = self.getScale()

        if max_width is None:
            max_width = 500

        band_names = ee_object.bandNames().getInfo()

        coordinates = []
        markers = []
        marker_cluster = MarkerCluster(name="Marker Cluster")
        self.last_click = []
        self.all_clicks = []
        self.add_layer(marker_cluster)

        def handle_interaction(**kwargs2):
            latlon = kwargs2.get("coordinates")

            if kwargs2.get("type") == "click":
                try:
                    coordinates.append(latlon)
                    self.last_click = latlon
                    self.all_clicks = coordinates
                    markers.append(Marker(location=latlon))
                    marker_cluster.markers = markers
                    self.default_style = {"cursor": "wait"}
                    xy = ee.Geometry.Point(latlon[::-1])
                    dict_values = (
                        ee_object.sample(xy, scale=sample_scale)
                        .first()
                        .toDictionary()
                        .getInfo()
                    )
                    band_values = list(dict_values.values())
                    self.plot(
                        band_names,
                        band_values,
                        plot_type=plot_type,
                        overlay=overlay,
                        min_width=min_width,
                        max_width=max_width,
                        min_height=min_height,
                        max_height=max_height,
                        **kwargs
                    )
                    self.default_style = {"cursor": "crosshair"}
                except Exception as e:
                    if self.plot_widget is not None:
                        with self.plot_widget:
                            self.plot_widget.clear_output()
                            print("No data for the clicked location.")
                    else:
                        print(e)
                    self.default_style = {"cursor": "crosshair"}

        self.on_interaction(handle_interaction)

    def add_maker_cluster(self, event="click", add_marker=True):
        """Captures user inputs and add markers to the map.

        Args:
            event (str, optional): [description]. Defaults to 'click'.
            add_marker (bool, optional): If True, add markers to the map. Defaults to True.

        Returns:
            object: a marker cluster.
        """
        coordinates = []
        markers = []
        marker_cluster = MarkerCluster(name="Marker Cluster")
        self.last_click = []
        self.all_clicks = []
        if add_marker:
            self.add_layer(marker_cluster)

        def handle_interaction(**kwargs):
            latlon = kwargs.get("coordinates")

            if event == "click" and kwargs.get("type") == "click":
                coordinates.append(latlon)
                self.last_click = latlon
                self.all_clicks = coordinates
                if add_marker:
                    markers.append(Marker(location=latlon))
                    marker_cluster.markers = markers
            elif kwargs.get("type") == "mousemove":
                pass

        # cursor style: https://www.w3schools.com/cssref/pr_class_cursor.asp
        self.default_style = {"cursor": "crosshair"}
        self.on_interaction(handle_interaction)

    def set_control_visibility(
        self, layerControl=True, fullscreenControl=True, latLngPopup=True
    ):
        """Sets the visibility of the controls on the map.

        Args:
            layerControl (bool, optional): Whether to show the control that allows the user to toggle layers on/off. Defaults to True.
            fullscreenControl (bool, optional): Whether to show the control that allows the user to make the map full-screen. Defaults to True.
            latLngPopup (bool, optional): Whether to show the control that pops up the Lat/lon when the user clicks on the map. Defaults to True.
        """
        pass

    setControlVisibility = set_control_visibility

    def add_layer_control(self):
        """Adds the layer control to the map."""
        pass

    addLayerControl = add_layer_control

    def split_map(self, left_layer="HYBRID", right_layer="ESRI"):
        """Adds split map.

        Args:
            left_layer (str, optional): The layer tile layer. Defaults to 'HYBRID'.
            right_layer (str, optional): The right tile layer. Defaults to 'ESRI'.
        """
        try:
            self.remove_control(self.layer_control)
            self.remove_control(self.inspector_control)
            if left_layer in ee_basemaps.keys():
                left_layer = ee_basemaps[left_layer]

            if right_layer in ee_basemaps.keys():
                right_layer = ee_basemaps[right_layer]

            control = ipyleaflet.SplitMapControl(
                left_layer=left_layer, right_layer=right_layer
            )
            self.add_control(control)

        except Exception as e:
            print(e)
            print("The provided layers are invalid!")

    def ts_inspector(
        self, left_ts, right_ts, left_names, right_names, left_vis={}, right_vis={}
    ):
        """Creates a split-panel map for inspecting timeseries images.

        Args:
            left_ts (object): An ee.ImageCollection to show on the left panel.
            right_ts (object): An ee.ImageCollection to show on the right panel.
            left_names (list): A list of names to show under the left dropdown.
            right_names (list): A list of names to show under the right dropdown.
            left_vis (dict, optional): Visualization parameters for the left layer. Defaults to {}.
            right_vis (dict, optional): Visualization parameters for the right layer. Defaults to {}.
        """
        left_count = int(left_ts.size().getInfo())
        right_count = int(right_ts.size().getInfo())

        if left_count != len(left_names):
            print(
                "The number of images in left_ts must match the number of layer names in left_names."
            )
            return
        if right_count != len(right_names):
            print(
                "The number of images in right_ts must match the number of layer names in right_names."
            )
            return

        left_layer = TileLayer(
            url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
            attribution="Google",
            name="Google Maps",
        )
        right_layer = TileLayer(
            url="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
            attribution="Google",
            name="Google Maps",
        )

        self.clear_controls()
        left_dropdown = widgets.Dropdown(options=left_names, value=None)
        right_dropdown = widgets.Dropdown(options=right_names, value=None)
        left_dropdown.layout.max_width = "130px"
        right_dropdown.layout.max_width = "130px"

        left_control = WidgetControl(widget=left_dropdown, position="topleft")
        right_control = WidgetControl(widget=right_dropdown, position="topright")

        self.add_control(control=left_control)
        self.add_control(control=right_control)

        self.add_control(ZoomControl(position="topleft"))
        self.add_control(ScaleControl(position="bottomleft"))
        self.add_control(FullScreenControl())

        def left_dropdown_change(change):
            left_dropdown_index = left_dropdown.index
            if left_dropdown_index is not None and left_dropdown_index >= 0:
                try:
                    if isinstance(left_ts, ee.ImageCollection):
                        left_image = left_ts.toList(left_ts.size()).get(
                            left_dropdown_index
                        )
                    elif isinstance(left_ts, ee.List):
                        left_image = left_ts.get(left_dropdown_index)
                    else:
                        print("The left_ts argument must be an ImageCollection.")
                        return

                    if isinstance(left_image, ee.ImageCollection):
                        left_image = ee.Image(left_image.mosaic())
                    elif isinstance(left_image, ee.Image):
                        pass
                    else:
                        left_image = ee.Image(left_image)

                    left_image = ee_tile_layer(
                        left_image, left_vis, left_names[left_dropdown_index]
                    )
                    left_layer.url = left_image.url
                except Exception as e:
                    print(e)
                    return

        left_dropdown.observe(left_dropdown_change, names="value")

        def right_dropdown_change(change):
            right_dropdown_index = right_dropdown.index
            if right_dropdown_index is not None and right_dropdown_index >= 0:
                try:
                    if isinstance(right_ts, ee.ImageCollection):
                        right_image = right_ts.toList(left_ts.size()).get(
                            right_dropdown_index
                        )
                    elif isinstance(right_ts, ee.List):
                        right_image = right_ts.get(right_dropdown_index)
                    else:
                        print("The left_ts argument must be an ImageCollection.")
                        return

                    if isinstance(right_image, ee.ImageCollection):
                        right_image = ee.Image(right_image.mosaic())
                    elif isinstance(right_image, ee.Image):
                        pass
                    else:
                        right_image = ee.Image(right_image)

                    right_image = ee_tile_layer(
                        right_image, right_vis, right_names[right_dropdown_index]
                    )
                    right_layer.url = right_image.url
                except Exception as e:
                    print(e)
                    return

        right_dropdown.observe(right_dropdown_change, names="value")

        try:

            split_control = ipyleaflet.SplitMapControl(
                left_layer=left_layer, right_layer=right_layer
            )
            self.add_control(split_control)

        except Exception as e:
            print(e)

    def basemap_demo(self):
        """A demo for using geemap basemaps."""
        dropdown = widgets.Dropdown(
            options=list(ee_basemaps.keys()), value="HYBRID", description="Basemaps"
        )

        def on_click(change):
            basemap_name = change["new"]
            old_basemap = self.layers[-1]
            self.substitute_layer(old_basemap, ee_basemaps[basemap_name])

        dropdown.observe(on_click, "value")
        basemap_control = WidgetControl(widget=dropdown, position="topright")
        self.remove_control(self.inspector_control)
        # self.remove_control(self.layer_control)
        self.add_control(basemap_control)

    def add_legend(
        self,
        legend_title="Legend",
        legend_dict=None,
        legend_keys=None,
        legend_colors=None,
        position="bottomright",
        builtin_legend=None,
        **kwargs
    ):
        """Adds a customized basemap to the map.

        Args:
            legend_title (str, optional): Title of the legend. Defaults to 'Legend'.
            legend_dict (dict, optional): A dictionary containing legend items as keys and color as values. If provided, legend_keys and legend_colors will be ignored. Defaults to None.
            legend_keys (list, optional): A list of legend keys. Defaults to None.
            legend_colors (list, optional): A list of legend colors. Defaults to None.
            position (str, optional): Position of the legend. Defaults to 'bottomright'.
            builtin_legend (str, optional): Name of the builtin legend to add to the map. Defaults to None.

        """
        import pkg_resources
        from IPython.display import display

        pkg_dir = os.path.dirname(
            pkg_resources.resource_filename("geemap", "geemap.py")
        )
        legend_template = os.path.join(pkg_dir, "data/template/legend.html")

        # print(kwargs['min_height'])

        if "min_width" not in kwargs.keys():
            min_width = None
        else:
            min_wdith = kwargs["min_width"]
        if "max_width" not in kwargs.keys():
            max_width = None
        else:
            max_width = kwargs["max_width"]
        if "min_height" not in kwargs.keys():
            min_height = None
        else:
            min_height = kwargs["min_height"]
        if "max_height" not in kwargs.keys():
            max_height = None
        else:
            max_height = kwargs["max_height"]
        if "height" not in kwargs.keys():
            height = None
        else:
            height = kwargs["height"]
        if "width" not in kwargs.keys():
            width = None
        else:
            width = kwargs["width"]

        if width is None:
            max_width = "300px"
        if height is None:
            max_height = "400px"

        if not os.path.exists(legend_template):
            print("The legend template does not exist.")
            return

        if legend_keys is not None:
            if not isinstance(legend_keys, list):
                print("The legend keys must be a list.")
                return
        else:
            legend_keys = ["One", "Two", "Three", "Four", "ect"]

        if legend_colors is not None:
            if not isinstance(legend_colors, list):
                print("The legend colors must be a list.")
                return
            elif all(isinstance(item, tuple) for item in legend_colors):
                try:
                    legend_colors = [rgb_to_hex(x) for x in legend_colors]
                except Exception as e:
                    print(e)
            elif all(
                (item.startswith("#") and len(item) == 7) for item in legend_colors
            ):
                pass
            elif all((len(item) == 6) for item in legend_colors):
                pass
            else:
                print("The legend colors must be a list of tuples.")
                return
        else:
            legend_colors = ["#8DD3C7", "#FFFFB3", "#BEBADA", "#FB8072", "#80B1D3"]

        if len(legend_keys) != len(legend_colors):
            print("The legend keys and values must be the same length.")
            return

        allowed_builtin_legends = builtin_legends.keys()
        if builtin_legend is not None:
            # builtin_legend = builtin_legend.upper()
            if builtin_legend not in allowed_builtin_legends:
                print(
                    "The builtin legend must be one of the following: {}".format(
                        ", ".join(allowed_builtin_legends)
                    )
                )
                return
            else:
                legend_dict = builtin_legends[builtin_legend]
                legend_keys = list(legend_dict.keys())
                legend_colors = list(legend_dict.values())

        if legend_dict is not None:
            if not isinstance(legend_dict, dict):
                print("The legend dict must be a dictionary.")
                return
            else:
                legend_keys = list(legend_dict.keys())
                legend_colors = list(legend_dict.values())
                if all(isinstance(item, tuple) for item in legend_colors):
                    try:
                        legend_colors = [rgb_to_hex(x) for x in legend_colors]
                    except Exception as e:
                        print(e)

        allowed_positions = ["topleft", "topright", "bottomleft", "bottomright"]
        if position not in allowed_positions:
            print(
                "The position must be one of the following: {}".format(
                    ", ".join(allowed_positions)
                )
            )
            return

        header = []
        content = []
        footer = []

        with open(legend_template) as f:
            lines = f.readlines()
            lines[3] = lines[3].replace("Legend", legend_title)
            header = lines[:6]
            footer = lines[11:]

        for index, key in enumerate(legend_keys):
            color = legend_colors[index]
            if not color.startswith("#"):
                color = "#" + color
            item = "      <li><span style='background:{};'></span>{}</li>\n".format(
                color, key
            )
            content.append(item)

        legend_html = header + content + footer
        legend_text = "".join(legend_html)

        try:
            if self.legend_control is not None:
                legend_widget = self.legend_widget
                legend_widget.close()
                self.remove_control(self.legend_control)

            legend_output_widget = widgets.Output(
                layout={
                    "border": "1px solid black",
                    "max_width": max_width,
                    "min_width": min_width,
                    "max_height": max_height,
                    "min_height": min_height,
                    "height": height,
                    "width": width,
                    "overflow": "scroll",
                }
            )
            legend_control = WidgetControl(
                widget=legend_output_widget, position=position
            )
            legend_widget = widgets.HTML(value=legend_text)
            with legend_output_widget:
                display(legend_widget)

            self.legend_widget = legend_output_widget
            self.legend_control = legend_control
            self.add_control(legend_control)

        except Exception as e:
            print(e)

    def image_overlay(self, url, bounds, name):
        """Overlays an image from the Internet or locally on the map.

        Args:
            url (str): http URL or local file path to the image.
            bounds (tuple): bounding box of the image in the format of (lower_left(lat, lon), upper_right(lat, lon)), such as ((13, -130), (32, -100)).
            name (str): name of the layer to show on the layer control.
        """
        from base64 import b64encode
        from PIL import Image, ImageSequence
        from io import BytesIO

        try:
            if not url.startswith("http"):

                if not os.path.exists(url):
                    print("The provided file does not exist.")
                    return

                ext = os.path.splitext(url)[1][1:]  # file extension
                image = Image.open(url)

                f = BytesIO()
                if ext.lower() == "gif":
                    frames = []
                    # Loop over each frame in the animated image
                    for frame in ImageSequence.Iterator(image):
                        frame = frame.convert("RGBA")
                        b = BytesIO()
                        frame.save(b, format="gif")
                        frame = Image.open(b)
                        frames.append(frame)
                    frames[0].save(
                        f, format="GIF", save_all=True, append_images=frames[1:], loop=0
                    )
                else:
                    image.save(f, ext)

                data = b64encode(f.getvalue())
                data = data.decode("ascii")
                url = "data:image/{};base64,".format(ext) + data
            img = ipyleaflet.ImageOverlay(url=url, bounds=bounds, name=name)
            self.add_layer(img)
        except Exception as e:
            print(e)

    def video_overlay(self, url, bounds, name):
        """Overlays a video from the Internet on the map.

        Args:
            url (str): http URL of the video, such as "https://www.mapbox.com/bites/00188/patricia_nasa.webm"
            bounds (tuple): bounding box of the video in the format of (lower_left(lat, lon), upper_right(lat, lon)), such as ((13, -130), (32, -100)).
            name (str): name of the layer to show on the layer control.
        """
        try:
            video = ipyleaflet.VideoOverlay(url=url, bounds=bounds, name=name)
            self.add_layer(video)
        except Exception as e:
            print(e)

    def add_landsat_ts_gif(
        self,
        layer_name="Timelapse",
        roi=None,
        label=None,
        start_year=1984,
        end_year=2019,
        start_date="06-10",
        end_date="09-20",
        bands=["NIR", "Red", "Green"],
        vis_params=None,
        dimensions=768,
        frames_per_second=10,
        font_size=30,
        font_color="white",
        add_progress_bar=True,
        progress_bar_color="white",
        progress_bar_height=5,
        out_gif=None,
        download=False,
        apply_fmask=True,
        nd_bands=None,
        nd_threshold=0,
        nd_palette=["black", "blue"],
    ):
        """Adds a Landsat timelapse to the map.

        Args:
            layer_name (str, optional): Layer name to show under the layer control. Defaults to 'Timelapse'.
            roi (object, optional): Region of interest to create the timelapse. Defaults to None.
            label (str, optional): A label to shown on the GIF, such as place name. Defaults to None.
            start_year (int, optional): Starting year for the timelapse. Defaults to 1984.
            end_year (int, optional): Ending year for the timelapse. Defaults to 2019.
            start_date (str, optional): Starting date (month-day) each year for filtering ImageCollection. Defaults to '06-10'.
            end_date (str, optional): Ending date (month-day) each year for filtering ImageCollection. Defaults to '09-20'.
            bands (list, optional): Three bands selected from ['Blue', 'Green', 'Red', 'NIR', 'SWIR1', 'SWIR2', 'pixel_qa']. Defaults to ['NIR', 'Red', 'Green'].
            vis_params (dict, optional): Visualization parameters. Defaults to None.
            dimensions (int, optional): a number or pair of numbers in format WIDTHxHEIGHT) Maximum dimensions of the thumbnail to render, in pixels. If only one number is passed, it is used as the maximum, and the other dimension is computed by proportional scaling. Defaults to 768.
            frames_per_second (int, optional): Animation speed. Defaults to 10.
            font_size (int, optional): Font size of the animated text and label. Defaults to 30.
            font_color (str, optional): Font color of the animated text and label. Defaults to 'black'.
            add_progress_bar (bool, optional): Whether to add a progress bar at the bottom of the GIF. Defaults to True.
            progress_bar_color (str, optional): Color for the progress bar. Defaults to 'white'.
            progress_bar_height (int, optional): Height of the progress bar. Defaults to 5.
            out_gif (str, optional): File path to the output animated GIF. Defaults to None.
            download (bool, optional): Whether to download the gif. Defaults to False.
            apply_fmask (bool, optional): Whether to apply Fmask (Function of mask) for automated clouds, cloud shadows, snow, and water masking.
            nd_bands (list, optional): A list of names specifying the bands to use, e.g., ['Green', 'SWIR1']. The normalized difference is computed as (first − second) / (first + second). Note that negative input values are forced to 0 so that the result is confined to the range (-1, 1).
            nd_threshold (float, optional): The threshold for extacting pixels from the normalized difference band.
            nd_palette (str, optional): The color palette to use for displaying the normalized difference band.

        """
        try:

            if roi is None:
                if self.draw_last_feature is not None:
                    feature = self.draw_last_feature
                    roi = feature.geometry()
                else:
                    roi = ee.Geometry.Polygon(
                        [
                            [
                                [-115.471773, 35.892718],
                                [-115.471773, 36.409454],
                                [-114.271283, 36.409454],
                                [-114.271283, 35.892718],
                                [-115.471773, 35.892718],
                            ]
                        ],
                        None,
                        False,
                    )
            elif isinstance(roi, ee.Feature) or isinstance(roi, ee.FeatureCollection):
                roi = roi.geometry()
            elif isinstance(roi, ee.Geometry):
                pass
            else:
                print("The provided roi is invalid. It must be an ee.Geometry")
                return

            geojson = ee_to_geojson(roi)
            bounds = minimum_bounding_box(geojson)
            geojson = adjust_longitude(geojson)
            roi = ee.Geometry(geojson)

            in_gif = landsat_ts_gif(
                roi=roi,
                out_gif=out_gif,
                start_year=start_year,
                end_year=end_year,
                start_date=start_date,
                end_date=end_date,
                bands=bands,
                vis_params=vis_params,
                dimensions=dimensions,
                frames_per_second=frames_per_second,
                apply_fmask=apply_fmask,
                nd_bands=nd_bands,
                nd_threshold=nd_threshold,
                nd_palette=nd_palette,
            )
            in_nd_gif = in_gif.replace(".gif", "_nd.gif")

            print("Adding animated text to GIF ...")
            add_text_to_gif(
                in_gif,
                in_gif,
                xy=("2%", "2%"),
                text_sequence=start_year,
                font_size=font_size,
                font_color=font_color,
                duration=int(1000 / frames_per_second),
                add_progress_bar=add_progress_bar,
                progress_bar_color=progress_bar_color,
                progress_bar_height=progress_bar_height,
            )
            if nd_bands is not None:
                add_text_to_gif(
                    in_nd_gif,
                    in_nd_gif,
                    xy=("2%", "2%"),
                    text_sequence=start_year,
                    font_size=font_size,
                    font_color=font_color,
                    duration=int(1000 / frames_per_second),
                    add_progress_bar=add_progress_bar,
                    progress_bar_color=progress_bar_color,
                    progress_bar_height=progress_bar_height,
                )

            if label is not None:
                add_text_to_gif(
                    in_gif,
                    in_gif,
                    xy=("2%", "90%"),
                    text_sequence=label,
                    font_size=font_size,
                    font_color=font_color,
                    duration=int(1000 / frames_per_second),
                    add_progress_bar=add_progress_bar,
                    progress_bar_color=progress_bar_color,
                    progress_bar_height=progress_bar_height,
                )
                # if nd_bands is not None:
                #     add_text_to_gif(in_nd_gif, in_nd_gif, xy=('2%', '90%'), text_sequence=label,
                #                     font_size=font_size, font_color=font_color, duration=int(1000 / frames_per_second), add_progress_bar=add_progress_bar, progress_bar_color=progress_bar_color, progress_bar_height=progress_bar_height)

            if is_tool("ffmpeg"):
                reduce_gif_size(in_gif)
                if nd_bands is not None:
                    reduce_gif_size(in_nd_gif)

            print("Adding GIF to the map ...")
            self.image_overlay(url=in_gif, bounds=bounds, name=layer_name)
            if nd_bands is not None:
                self.image_overlay(
                    url=in_nd_gif, bounds=bounds, name=layer_name + " ND"
                )
            print("The timelapse has been added to the map.")

            if download:
                link = create_download_link(
                    in_gif, title="Click here to download the Landsat timelapse: "
                )
                display(link)
                if nd_bands is not None:
                    link2 = create_download_link(
                        in_nd_gif,
                        title="Click here to download the Normalized Difference Index timelapse: ",
                    )
                    display(link2)

        except Exception as e:
            print(e)

    def to_html(self, outfile, title="My Map", width="100%", height="880px"):
        """Saves the map as a HTML file.

        Args:
            outfile (str): The output file path to the HTML file.
            title (str, optional): The title of the HTML file. Defaults to 'My Map'.
            width (str, optional): The width of the map in pixels or percentage. Defaults to '100%'.
            height (str, optional): The height of the map in pixels. Defaults to '880px'.
        """
        try:

            if not outfile.endswith(".html"):
                print("The output file must end with .html")
                return

            out_dir = os.path.dirname(outfile)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)

            before_width = self.layout.width
            before_height = self.layout.height

            if not isinstance(width, str):
                print("width must be a string.")
                return
            elif width.endswith("px") or width.endswith("%"):
                pass
            else:
                print("width must end with px or %")
                return

            if not isinstance(height, str):
                print("height must be a string.")
                return
            elif not height.endswith("px"):
                print("height must end with px")
                return

            self.layout.width = width
            self.layout.height = height

            self.save(outfile, title=title)

            self.layout.width = before_width
            self.layout.height = before_height

        except Exception as e:
            print(e)

    def to_image(self, outfile=None, monitor=1):
        """Saves the map as a PNG or JPG image.

        Args:
            outfile (str, optional): The output file path to the image. Defaults to None.
            monitor (int, optional): The monitor to take the screenshot. Defaults to 1.
        """
        if outfile is None:
            outfile = os.path.join(os.getcwd(), "my_map.png")

        if outfile.endswith(".png") or outfile.endswith(".jpg"):
            pass
        else:
            print("The output file must be a PNG or JPG image.")
            return

        work_dir = os.path.dirname(outfile)
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

        screenshot = screen_capture(outfile, monitor)
        self.screenshot = screenshot

    def toolbar_reset(self):
        """Reset the toolbar so that no tool is selected."""
        toolbar_grid = self.toolbar
        for tool in toolbar_grid.children:
            tool.value = False

    def add_raster(
        self, image, bands=None, layer_name=None, colormap=None, x_dim="x", y_dim="y"
    ):
        """Adds a local raster dataset to the map.

        Args:
            image (str): The image file path.
            bands (int or list, optional): The image bands to use. It can be either a nubmer (e.g., 1) or a list (e.g., [3, 2, 1]). Defaults to None.
            layer_name (str, optional): The layer name to use for the raster. Defaults to None.
            colormap (str, optional): The name of the colormap to use for the raster, such as 'gray' and 'terrain'. More can be found at https://matplotlib.org/3.1.0/tutorials/colors/colormaps.html. Defaults to None.
            x_dim (str, optional): The x dimension. Defaults to 'x'.
            y_dim (str, optional): The y dimension. Defaults to 'y'.
        """
        try:
            import xarray_leaflet

        except:
            # import platform
            # if platform.system() != "Windows":
            #     # install_from_github(
            #     #     url='https://github.com/davidbrochart/xarray_leaflet')
            #     check_install('xarray_leaflet')
            #     import xarray_leaflet
            # else:
            print(
                "You need to install xarray_leaflet first. See https://github.com/davidbrochart/xarray_leaflet"
            )
            print(
                "Try the following to install xarray_leaflet: \n\nconda install -c conda-forge xarray_leaflet"
            )
            return

        import warnings
        import numpy as np
        import rioxarray
        import xarray as xr
        import matplotlib.pyplot as plt

        warnings.simplefilter("ignore")

        if not os.path.exists(image):
            print("The image file does not exist.")
            return

        if colormap is None:
            colormap = plt.cm.inferno

        if layer_name is None:
            layer_name = "Layer_" + random_string()

        if isinstance(colormap, str):
            colormap = plt.cm.get_cmap(name=colormap)

        da = rioxarray.open_rasterio(image, masked=True)

        # print(da.rio.nodata)

        multi_band = False
        if len(da.band) > 1:
            multi_band = True
            if bands is None:
                bands = [3, 2, 1]
        else:
            bands = 1

        if multi_band:
            da = da.rio.write_nodata(0)
        else:
            da = da.rio.write_nodata(np.nan)
        da = da.sel(band=bands)

        # crs = da.rio.crs
        # nan = da.attrs['nodatavals'][0]
        # da = da / da.max()
        # # if multi_band:
        # da = xr.where(da == nan, np.nan, da)
        # da = da.rio.write_nodata(0)
        # da = da.rio.write_crs(crs)

        if multi_band:
            layer = da.leaflet.plot(self, x_dim=x_dim, y_dim=y_dim, rgb_dim="band")
        else:
            layer = da.leaflet.plot(self, x_dim=x_dim, y_dim=y_dim, colormap=colormap)

        layer.name = layer_name

    def remove_drawn_features(self):
        """Removes user-drawn geometries from the map"""
        if self.draw_layer is not None:
            self.remove_layer(self.draw_layer)
            self.draw_count = 0
            self.draw_features = []
            self.draw_last_feature = None
            self.draw_layer = None
            self.draw_last_json = None
            self.draw_last_bounds = None
            self.user_roi = None
            self.user_rois = None
            self.chart_values = []
            self.chart_points = []
            self.chart_labels = None

    def remove_last_drawn(self):
        """Removes user-drawn geometries from the map"""
        if self.draw_layer is not None:
            collection = ee.FeatureCollection(self.draw_features[:-1])
            ee_draw_layer = ee_tile_layer(
                collection, {"color": "blue"}, "Drawn Features", True, 0.5
            )
            if self.draw_count == 1:
                self.remove_drawn_features()
            else:
                self.substitute_layer(self.draw_layer, ee_draw_layer)
                self.draw_layer = ee_draw_layer
                self.draw_count -= 1
                self.draw_features = self.draw_features[:-1]
                self.draw_last_feature = self.draw_features[-1]
                self.draw_layer = ee_draw_layer
                self.draw_last_json = None
                self.draw_last_bounds = None
                self.user_roi = ee.Feature(
                    collection.toList(collection.size()).get(
                        collection.size().subtract(1)
                    )
                ).geometry()
                self.user_rois = collection
                self.chart_values = self.chart_values[:-1]
                self.chart_points = self.chart_points[:-1]
                # self.chart_labels = None

    def extract_values_to_points(self, filename):
        """Exports pixel values to a csv file based on user-drawn geometries.

        Args:
            filename (str): The output file path to the csv file or shapefile.
        """
        import csv

        filename = os.path.abspath(filename)
        allowed_formats = ["csv", "shp"]
        ext = filename[-3:]

        if ext not in allowed_formats:
            print(
                "The output file must be one of the following: {}".format(
                    ", ".join(allowed_formats)
                )
            )
            return

        out_dir = os.path.dirname(filename)
        out_csv = filename[:-3] + "csv"
        out_shp = filename[:-3] + "shp"
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        count = len(self.chart_points)
        out_list = []
        if count > 0:
            header = ["id", "longitude", "latitude"] + self.chart_labels
            out_list.append(header)

            for i in range(0, count):
                id = i + 1
                line = [id] + self.chart_points[i] + self.chart_values[i]
                out_list.append(line)

            with open(out_csv, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerows(out_list)

            if ext == "csv":
                print("The csv file has been saved to: {}".format(out_csv))
            else:
                csv_to_shp(out_csv, out_shp)
                print("The shapefile has been saved to: {}".format(out_shp))


# The functions below are outside the Map class.


def ee_tile_layer(
    ee_object, vis_params={}, name="Layer untitled", shown=True, opacity=1.0
):
    """Converts and Earth Engine layer to ipyleaflet TileLayer.

    Args:
        ee_object (Collection|Feature|Image|MapId): The object to add to the map.
        vis_params (dict, optional): The visualization parameters. Defaults to {}.
        name (str, optional): The name of the layer. Defaults to 'Layer untitled'.
        shown (bool, optional): A flag indicating whether the layer should be on by default. Defaults to True.
        opacity (float, optional): The layer's opacity represented as a number between 0 and 1. Defaults to 1.
    """
    # ee_initialize()

    image = None

    if (
        not isinstance(ee_object, ee.Image)
        and not isinstance(ee_object, ee.ImageCollection)
        and not isinstance(ee_object, ee.FeatureCollection)
        and not isinstance(ee_object, ee.Feature)
        and not isinstance(ee_object, ee.Geometry)
    ):
        err_str = "\n\nThe image argument in 'addLayer' function must be an instace of one of ee.Image, ee.Geometry, ee.Feature or ee.FeatureCollection."
        raise AttributeError(err_str)

    if (
        isinstance(ee_object, ee.geometry.Geometry)
        or isinstance(ee_object, ee.feature.Feature)
        or isinstance(ee_object, ee.featurecollection.FeatureCollection)
    ):
        features = ee.FeatureCollection(ee_object)

        width = 2

        if "width" in vis_params:
            width = vis_params["width"]

        color = "000000"

        if "color" in vis_params:
            color = vis_params["color"]

        image_fill = features.style(**{"fillColor": color}).updateMask(
            ee.Image.constant(0.5)
        )
        image_outline = features.style(
            **{"color": color, "fillColor": "00000000", "width": width}
        )

        image = image_fill.blend(image_outline)
    elif isinstance(ee_object, ee.image.Image):
        image = ee_object
    elif isinstance(ee_object, ee.imagecollection.ImageCollection):
        image = ee_object.mosaic()

    map_id_dict = ee.Image(image).getMapId(vis_params)
    tile_layer = ipyleaflet.TileLayer(
        url=map_id_dict["tile_fetcher"].url_format,
        attribution="Google Earth Engine",
        name=name,
        opacity=opacity,
        visible=True
        # visible=shown
    )
    return tile_layer
