"""Weather, from Open-Meteo (https://open-meteo.com): free, no account or key."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from jarvis.core.tools import AUTO, ToolContext, ToolResult, tool

# Open-Meteo's numeric weather codes, in plain words.
CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
    82: "violent showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def _get(url: str, params: dict) -> dict:
    """Kept separate so tests can replace it."""
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=20) as response:
        return json.load(response)


@tool(
    name="weather",
    description="Current weather and a three-day forecast for a place. Defaults to the user's home location.",
    input_schema={
        "type": "object",
        "properties": {"place": {"type": "string", "description": "A city or town. Omit for the user's location."}},
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Check the weather in {a.get('place') or c.settings.location}",
)
def weather(args: dict, ctx: ToolContext) -> ToolResult:
    place = (args.get("place") or ctx.settings.location).strip()
    try:
        found = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": place, "count": 1}).get("results")
        if not found:
            return ToolResult(f"No place called {place!r} was found.", is_error=True)
        spot = found[0]
        data = _get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": spot["latitude"], "longitude": spot["longitude"], "timezone": "auto", "forecast_days": 3,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            },
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return ToolResult(f"The weather service could not be reached ({getattr(exc, 'reason', exc)}).", is_error=True)
    if data.get("error"):
        return ToolResult(f"The weather service refused: {data.get('reason')}", is_error=True)

    now, daily = data["current"], data["daily"]
    lines = [
        f"{spot['name']}, {spot.get('country', '')}: now {round(now['temperature_2m'])}°C "
        f"(feels like {round(now['apparent_temperature'])}°C), {CODES.get(now['weather_code'], 'unknown conditions')}, "
        f"humidity {now['relative_humidity_2m']}%, wind {round(now['wind_speed_10m'])} km/h."
    ]
    for i, day in enumerate(daily["time"]):
        label = "Today" if i == 0 else "Tomorrow" if i == 1 else day
        rain = daily["precipitation_probability_max"][i]
        lines.append(
            f"{label}: {CODES.get(daily['weather_code'][i], 'unknown')}, {round(daily['temperature_2m_min'][i])} to "
            f"{round(daily['temperature_2m_max'][i])}°C" + (f", {rain}% chance of rain" if rain else "") + "."
        )
    return ToolResult("\n".join(lines))
