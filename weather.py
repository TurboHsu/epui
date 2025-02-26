import datetime
import json
from functools import cache

import requests

import resources
from ui import VGroup, Context, ViewMeasurement, ViewAlignmentHorizontal, ImageView, ViewSize, TextView, HGroup, \
    Surface, ViewAlignmentVertical, ImageDraw, Image, COLOR_TRANSPARENT, overlay
from charts import TrendChartsView, ChartsLineType, ChartsConfiguration, Axis, AxisPosition

from enum import Enum
import time as pytime
from typing import *


class Location:
    def __init__(self, latitude: float, longitude: float, friendly_name: str = None):
        self.latitude = latitude
        self.longitude = longitude
        self.friendly_name = friendly_name


class Day(Enum):
    CLEAR = 0
    CLOUDY = 1
    LIGHTLY_RAINY = 2
    RAINY = 3
    HEAVILY_RAINY = 4
    SNOWY_RAINY = 5
    LIGHTLY_SNOWY = 6
    SNOWY = 7
    HEAVILY_SNOWY = 8
    HAZY = 9
    FOGGY = 10
    DUSTY = 11
    SANDY = 12
    WINDY = 13
    UNKNOWN = 14


class TemperatureUnit(Enum):
    CELSIUS = 0
    FAHRENHEIT = 1
    KELVIN = 2


class WeatherEffectiveness(Enum):
    CURRENT = 0
    HOURLY = 1
    DAILY = 2
    ANY = 3


class Weather:
    def __init__(self,
                 time: pytime.struct_time = pytime.localtime(),
                 effect: WeatherEffectiveness = WeatherEffectiveness.CURRENT,
                 day: Day = Day.CLEAR,
                 temperature: float = 22,
                 humidity: float = 0.2,
                 pressure: float = 10,
                 uv_index: int = 5):
        """
        All these default parameters are for testing purpose, and
        should be set by the weather provider.
        :param day: the sky-con
        :param effect: role this weather data's playing
        :param temperature: value of temperature, unit dependent on the provider
        :param humidity: range from 0-1 in percentage
        :param pressure: air pressure in hPa
        :param uv_index: range from 0-10, aka ultraviolet index
        """
        self.time = time
        self.effect = effect
        self.day = day
        self.temperature = temperature
        self.humidity = humidity
        self.pressure = pressure
        self.uv_index = uv_index


class WeatherProvider:
    def __init__(self, location: Location, temperature_unit: TemperatureUnit):
        self.__location = location
        self.__temperature_unit = temperature_unit

    def get_location(self):
        return self.__location

    def get_temperature_unit(self):
        return self.__temperature_unit

    def get_weather(self) -> List[Weather]:
        """
        Refresh the weather query
        :return: list of weather infos, sorted from the most recent to the farthest future,
         length of which is undefined
        """
        pass


class CachedWeatherProvider(WeatherProvider):
    """
    An abstract class on which cached weather providers are based

    If a provider is cached, it responds the same result in certain
    condition, in this case, time
    """
    def __init__(self, location: Location, temperature_unit: TemperatureUnit, cache_invalidate_interval: float = 3600):
        """
        Creates a cached provider
        :param location: what place the weather info applies to
        :param temperature_unit: which temperature unit the info adopts
        :param cache_invalidate_interval: the cache's lifespan
        """
        super().__init__(location, temperature_unit)
        self.cache_invalidation = cache_invalidate_interval
        self.__update_time = None
        self.__cache = None

    def invalidate(self) -> List[Weather]:
        """
        Alias of `WeatherProvider.get_weather`

        Should override this function to work properly
        """
        pass

    def get_weather(self):
        if self.__update_time is not None \
                and pytime.time() - self.__update_time < self.cache_invalidation:
            return self.__cache
        self.__update_time = pytime.time()
        new_data = self.invalidate()
        self.__cache = new_data
        return new_data


class DirectWeatherProvider(WeatherProvider):
    """
    A weather provider that serves a constant result
    """
    def __init__(self, weather: Weather, location: Location = Location(0, 0, 'Test Land')):
        self.__weather = weather
        super().__init__(location, TemperatureUnit.CELSIUS)

    def get_weather(self) -> List[Weather]:
        return [self.__weather]


class CaiYunWeatherProvider(CachedWeatherProvider):
    """
    A real implementation of CaiYun Weather, a Chinese weather provider
    that offers free API access to personal developers
    """
    def __init__(self, location: Location, api_key: str, cache_invalidate_interval: float = 3600):
        """
        Create a CaiYun Weather provider
        :param location: what place the weather info applies to
        :param api_key: token to access the API. Get one in https://dashboard.caiyunapp.com/v1/token/
        :param cache_invalidate_interval: lifespan of the cache. See `CachedWeatherProvider`
        """
        super().__init__(location, TemperatureUnit.CELSIUS, cache_invalidate_interval)
        self.api_key = api_key

    def __get_api_url(self):
        return f'https://api.caiyunapp.com/v2.6/{self.api_key}/' \
               f'{self.get_location().longitude},{self.get_location().latitude}'

    @staticmethod
    def __caiyun_get_day(raw: str) -> Day:
        """
        See https://docs.caiyunapp.com/docs/tables/skycon/ for full list
        :param raw: CaiYun's response
        :return: my interface
        """
        raw = raw.lower()
        if 'clear' in raw:
            return Day.CLEAR
        elif 'cloudy' in raw:
            return Day.CLOUDY
        elif 'haze' in raw:
            return Day.HAZY
        elif raw == 'light_rain':
            return Day.LIGHTLY_RAINY
        elif raw == 'moderate_rain':
            return Day.RAINY
        elif raw == 'heavy_rain' or raw == 'storm_rain':
            return Day.HEAVILY_RAINY
        elif raw == 'fog':
            return Day.FOGGY
        elif raw == 'light_snow':
            return Day.LIGHTLY_SNOWY
        elif raw == 'moderate_snow':
            return Day.SNOWY
        elif raw == 'heavy_snow' or raw == 'storm_snow':
            return Day.HEAVILY_SNOWY
        elif raw == 'dust':
            return Day.DUSTY
        elif raw == 'sand':
            return Day.SANDY
        elif raw == 'wind':
            return Day.WINDY
        else:
            return Day.UNKNOWN

    def invalidate(self) -> List[Weather]:
        response = requests.get(self.__get_api_url() + '/weather?dailysteps=3&hourlysteps=24&minutely=false')
        if not response.ok:
            raise IOError('Realtime API not responding')

        api_callback = json.loads(response.text)
        result_realtime = api_callback['result']['realtime']
        result_hourly = api_callback['result']['hourly']
        result_daily = api_callback['result']['daily']
        current_weather = Weather(
            time=pytime.localtime(),
            effect=WeatherEffectiveness.CURRENT,
            temperature=result_realtime['temperature'],
            day=self.__caiyun_get_day(result_realtime['skycon']),
            humidity=result_realtime['humidity'],
            pressure=result_realtime['pressure'] / 100,
            uv_index=int(result_realtime['life_index']['ultraviolet']['index'])
        )
        hourly_weather = []
        daily_weather = []

        def parse(target_set: List[Weather], source: Dict, effect: WeatherEffectiveness):
            def pick(unit: Dict):
                if 'value' in unit:
                    return unit['value']
                elif 'avg' in unit:
                    return unit['avg']
                else:
                    raise ValueError(unit)

            for i in range(len(source['precipitation'])):
                precipitation = source['precipitation'][i]
                if 'datetime' in precipitation:
                    time = datetime.datetime.fromisoformat(precipitation['datetime']).timetuple()
                elif 'date' in precipitation:
                    time = datetime.datetime.fromisoformat(precipitation['date']).timetuple()
                else:
                    raise ValueError(precipitation)

                temperature = pick(source['temperature'][i])
                humidity = pick(source['humidity'][i])
                sky_con = pick(source['skycon'][i])
                pressure = pick(source['pressure'][i])
                target_set.append(
                    Weather(
                        time, effect, self.__caiyun_get_day(sky_con),
                        temperature, humidity, pressure, -1
                    )
                )

        parse(hourly_weather, result_hourly, WeatherEffectiveness.HOURLY)
        parse(daily_weather, result_daily, WeatherEffectiveness.DAILY)

        return [current_weather] + hourly_weather + daily_weather


def get_weather_icon(day: Day):
    if day == Day.CLEAR:
        return resources.get_image_tint('weather-sunny', 100)
    elif day == Day.CLOUDY:
        return resources.get_image('weather-cloudy')
    elif day == Day.RAINY or day == Day.LIGHTLY_RAINY:
        return resources.get_image('weather-rainy')
    elif day == Day.HEAVILY_RAINY:
        return resources.get_image('weather-pouring')
    elif day == Day.SNOWY or day == Day.LIGHTLY_SNOWY:
        return resources.get_image('weather-snowy')
    elif day == Day.HEAVILY_SNOWY:
        return resources.get_image('weather-snowy-heavy')
    elif day == Day.SNOWY_RAINY:
        return resources.get_image('weather-snowy-rainy')
    elif day == Day.WINDY:
        return resources.get_image('weather-windy')
    elif day == Day.HAZY:
        return resources.get_image('weather-hazy')
    elif day == Day.FOGGY:
        return resources.get_image('weather-fog')
    elif day == Day.DUSTY:
        return resources.get_image('weather-dust')
    else:
        return resources.get_image('weather-alert')


def get_day_name(day: Day):
    return day.name.replace('_', ' ').capitalize()


def get_unit_name(unit: TemperatureUnit):
    if unit == TemperatureUnit.CELSIUS:
        return '°C'
    elif unit == TemperatureUnit.FAHRENHEIT:
        return '°F'
    else:
        return 'K'


class LargeWeatherView(HGroup):
    def __init__(self, context: Context, provider: WeatherProvider,
                 effect: WeatherEffectiveness = WeatherEffectiveness.CURRENT,
                 prefer: ViewMeasurement = ViewMeasurement.default()):
        super().__init__(context, alignment=ViewAlignmentVertical.CENTER, prefer=prefer)
        self.__provider = provider
        self.__effect = effect
        self.__icon_view = None
        self.__day_label_view = None
        self.__subtitle_label_view = None
        self.refresh()

    def get_provider(self):
        return self.__provider

    def set_provider(self, provider: WeatherProvider):
        if self.__provider != provider:
            self.__provider = provider
            self.refresh()

    def get_effect(self):
        return self.__effect

    def set_effect(self, effect: WeatherEffectiveness):
        if self.__effect != effect:
            self.__effect = effect
            self.refresh()

    def __get_detailed_label(self, weather: Weather):
        return f'{weather.temperature} {get_unit_name(self.__provider.get_temperature_unit())}\n' \
               f'{int(weather.humidity * 100)} %\n' \
               f'{int(weather.pressure)} hPa\n' \
               f'{weather.uv_index} UV'

    def __add_views(self, weather: Weather):
        title_group = VGroup(self.context, alignment=ViewAlignmentHorizontal.RIGHT)
        self.__icon_view = ImageView(self.context,
                                     image=get_weather_icon(weather.day),
                                     prefer=ViewMeasurement.default(
                                         width=100,
                                         height=100
                                     ))
        self.__day_label_view = TextView(self.context,
                                         text=get_day_name(weather.day),
                                         font=TextView.default_font_bold,
                                         font_size=36)
        self.__subtitle_label_view = TextView(self.context,
                                              text=self.__get_detailed_label(weather),
                                              font_size=20,
                                              line_align=ViewAlignmentHorizontal.RIGHT)
        self.add_views(
            self.__icon_view,
            Surface(self.context,
                    prefer=ViewMeasurement.default(
                        width=3,
                        height=ViewSize.MATCH_PARENT,
                        margin_right=4,
                        margin_left=4,
                    ),
                    fill=0),
            title_group
        )
        title_group.add_views(
            self.__day_label_view,
            self.__subtitle_label_view
        )

    def refresh(self):
        weather = next(weather for weather in self.__provider.get_weather()
                       if weather.effect == self.__effect)

        if self.__icon_view is None:
            self.__add_views(weather)
        else:
            self.__icon_view.set_image(get_weather_icon(weather.day))
            self.__day_label_view.set_text(get_day_name(weather.day))
            self.__subtitle_label_view.set_text(self.__get_detailed_label(weather))

        self.invalidate()


class MiniWeatherView(VGroup):
    def __init__(self, context: Context, provider: WeatherProvider,
                 effect: WeatherEffectiveness = WeatherEffectiveness.CURRENT,
                 prefer: ViewMeasurement = ViewMeasurement.default()):
        self.__provider = provider
        self.__effect = effect
        self.__icon_view = None
        self.__label = None
        super().__init__(context, ViewAlignmentHorizontal.CENTER, prefer)
        self.refresh()

    def get_provider(self):
        return self.__provider

    def set_provider(self, provider: WeatherProvider):
        if self.__provider != provider:
            self.__provider = provider
            self.refresh()

    def get_effect(self):
        return self.__effect

    def set_effect(self, effect: WeatherEffectiveness):
        if self.__effect != effect:
            self.__effect = effect
            self.refresh()

    def __get_label(self, weather: Weather) -> str:
        return f'{get_day_name(weather.day)}\n' \
               f'{weather.temperature} {get_unit_name(self.__provider.get_temperature_unit())}'

    def __add_views(self, weather: Weather):
        self.__icon_view = ImageView(
            self.context,
            image=get_weather_icon(weather.day),
            prefer=ViewMeasurement.default(width=32, height=32)
        )
        self.__label = TextView(
            self.context,
            text=self.__get_label(weather),
            line_align=ViewAlignmentHorizontal.CENTER
        )
        self.add_views(self.__icon_view, self.__label)

    def refresh(self):
        weather = next(w for w in self.__provider.get_weather()
                       if self.__effect == WeatherEffectiveness.ANY or w.effect == self.__effect)
        if self.__icon_view is None:
            self.__add_views(weather)
        else:
            self.__icon_view.set_image(get_weather_icon(weather.day))
            self.__label.set_text(get_day_name(weather.day))


class WeatherTrendView(TrendChartsView):
    """
    A large view that contains a charts and its corresponding weather condition
    """
    def __init__(self, context: Context,
                 title: str, provider: WeatherProvider, effect: WeatherEffectiveness,
                 value: Callable[[Weather], float],
                 line_fill: int = 0, line_width: float = 2,
                 prefer: ViewMeasurement = ViewMeasurement.default(),
                 line_type: ChartsLineType = ChartsLineType.BEZIER_CURVE,
                 charts_configuration: ChartsConfiguration = None):
        """
        Create a WeatherTrendView
        :param context: where the view lives in
        :param title: the title, displayed right above the x-axis
        :param provider: the weather provider
        :param effect: only display what kind of weather info
        :param value: draws what data on the charts
        :param line_fill: what color is the charts line
        :param line_width: how bold the charts is
        :param prefer: the preferred view measurement
        :param line_type: what curve to draw the charts
        :param charts_configuration: detailed configuration of charts
        """
        if charts_configuration is None:
            charts_configuration=ChartsConfiguration(
                title=title,
                x_axis=Axis(position=AxisPosition.BOTTOM, label=''),
                y_axis=Axis.disabled()
            )
        
        super().__init__(
            context,
            data=[],
            line_width=line_width,
            line_fill=line_fill,
            line_type=line_type,
            prefer=prefer,
            configuration=charts_configuration
        )
        self.__provider = provider
        self.__effect = effect
        self.__value = value
        self.refresh()

    @staticmethod
    def label(w: Weather) -> int:
        current_time = pytime.localtime()
        return w.time.tm_hour - current_time.tm_hour + 24 * (w.time.tm_yday - current_time.tm_yday) + \
            365 * (w.time.tm_year - current_time.tm_year)

    @cache
    def __get_icon_sample(self) -> VGroup | None:
        weather = (w for w in self.__provider.get_weather()
                   if self.__effect == WeatherEffectiveness.ANY or w.effect == self.__effect)
        try:
            w = next(weather)
        except:
            return

        return self.__get_icon_view(w)

    def __get_icon_view(self, weather: Weather):
        group = VGroup(
            self.context,
            alignment=ViewAlignmentHorizontal.CENTER
        )
        time = TextView(
            self.context,
            text=pytime.strftime('%H:%M', weather.time)
        )
        view = MiniWeatherView(
            self.context, DirectWeatherProvider(weather),
            effect=WeatherEffectiveness.ANY
        )
        group.add_views(time, view)
        size = group.content_size()
        group.actual_measurement = ViewMeasurement.default(
            width=size[0],
            height=size[1]
        )
        return group

    def x_axis_size(self) -> float:
        sample = self.__get_icon_sample()
        if sample is None:
            return 0
        return sample.content_size()[1] + 10

    def draw_x_axis(self, canvas: ImageDraw.ImageDraw, bounds: Tuple[int, int], scale: float):
        sample_size = self.__get_icon_sample()
        if sample_size is None:
            return
        sample_size = sample_size.content_size()
        canvas.line(((0, self.get_line_width() / 2), (bounds[0], self.get_line_width() / 2)),
                    fill=self.get_line_fill(),
                    width=int(self.get_line_width() * scale))
        data = [w for w in self.__provider.get_weather()
                if self.__effect == WeatherEffectiveness.ANY or w.effect == self.__effect]
        stacked = int(bounds[0] / (sample_size[1] + 20))
        span = (bounds[0] - 20) / stacked
        for i in range(stacked):
            index = int(i / (stacked - 1) * (len(data) - 1))
            w = data[index]

            icon_view = self.__get_icon_view(w)
            icon_content_size = icon_view.content_size()
            view_canvas = Image.new('L', icon_content_size, color=COLOR_TRANSPARENT)
            canvas_draw = ImageDraw.Draw(view_canvas)
            icon_view.draw(canvas_draw, scale)
            overlay(canvas._image, view_canvas,
                    (int(i * span + 20 + span / 2 - icon_content_size[1] / 2), 10))

    def refresh(self):
        data = [(self.label(w), self.__value(w)) for w in self.__provider.get_weather()
                if self.__effect == WeatherEffectiveness.ANY or w.effect == self.__effect]
        self.set_data(data)
