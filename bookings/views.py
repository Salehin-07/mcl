import requests
import datetime
from django.shortcuts import render
from .models import Bookings

# ── Nominatim / OSRM helpers ──────────────────────────────────────────────────

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL      = "http://router.project-osrm.org/route/v1/driving"

# A descriptive User-Agent is required by Nominatim's usage policy.
# Replace the email with your own contact address.
HEADERS = {"User-Agent": "MelbourneLimoBooking/1.0 (contact@yourdomain.com.au)"}


def geocode(address):
    """
    Convert a plain-text address to (longitude, latitude) using Nominatim.
    Raises ValueError if the address cannot be resolved.
    """
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1, "countrycodes": "au"},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError(f"Address not found: {address}")
    return float(data[0]["lon"]), float(data[0]["lat"])


def get_route(origin, destination, waypoint=None):
    """
    Calculate driving distance (km) between origin and destination via OSRM.
    An optional waypoint (additional stop) is inserted between the two.
    Returns distance_km (float).
    """
    origin_coords = geocode(origin)
    dest_coords   = geocode(destination)

    # Build the coordinate string: lon,lat;lon,lat;...
    coords_parts = [f"{origin_coords[0]},{origin_coords[1]}"]
    if waypoint:
        wp = geocode(waypoint)
        coords_parts.append(f"{wp[0]},{wp[1]}")
    coords_parts.append(f"{dest_coords[0]},{dest_coords[1]}")

    coord_str = ";".join(coords_parts)

    resp = requests.get(
        f"{OSRM_URL}/{coord_str}",
        params={"overview": "false"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "Ok":
        raise ValueError("OSRM could not calculate a route for the given addresses.")

    distance_m = data["routes"][0]["distance"]
    return round(distance_m / 1000, 2)


# ── Main view ─────────────────────────────────────────────────────────────────

def bookings(request):
    """
    Two-step booking flow.

    GET              → Show the blank booking form.
    POST action=calculate → Geocode + route via Nominatim/OSRM, compute price,
                            store in session, render the price-preview page.
                            No DB write.
    POST action=confirm   → Read price from session, create Order, render
                            the confirmed page.
    """

    if request.method == "POST":
        action = request.POST.get("action", "calculate")

        # ── Extract all form fields ───────────────────────────────────────
        pickup       = request.POST.get("pickup_address", "").strip()
        destination  = request.POST.get("destination_address", "").strip()
        extra_stop   = request.POST.get("additional_stop", "").strip() or None
        service_type = request.POST.get("limo_service_type", "Sedan 1-5")
        has_baby_seat  = "baby_seat"   in request.POST
        is_return_ride = "return_ride" in request.POST

        form_data = {
            "passenger_name":       request.POST.get("passenger_name", ""),
            "passenger_number":     request.POST.get("passenger_number", ""),
            "passenger_email":      request.POST.get("passenger_email", ""),
            "number_of_passengers": request.POST.get("number_of_passengers", 2),
            "number_of_bags":       request.POST.get("number_of_bags", 2),
            "pickup_address":       pickup,
            "destination_address":  destination,
            "additional_stop":      extra_stop or "",
            "flight_number":        request.POST.get("flight_number", ""),
            "pickup_date":          request.POST.get("pickup_date", str(datetime.date.today())),
            "pickup_time":          request.POST.get("pickup_time", ""),
            "limo_service_type":    service_type,
            "baby_seat":            has_baby_seat,
            "return_ride":          is_return_ride,
            "special_instruction":  request.POST.get("special_instruction", ""),
            "vehicle_colour":       request.POST.get("vehicle_colour", ""),
            "wedding_ribbon":       request.POST.get("wedding_ribbon", ""),
            "special_signboard":    request.POST.get("special_signboard", ""),
            "name_on_card":         request.POST.get("name_on_card", ""),
            "card_type":            request.POST.get("card_type", ""),
            "card_number":          request.POST.get("card_number", ""),
        }

        # ── STEP 1: Calculate price ───────────────────────────────────────
        if action == "calculate":
            try:
                distance_km = get_route(pickup, destination, extra_stop)

                # NOTE: Toll detection is not available without Google Maps.
                # We expose it as a manual checkbox on the form instead
                # (see booking_form.html — user ticks "Route includes tolls").
                has_tolls = "has_tolls" in request.POST

                rates = {
                    "Sedan 1-5":    {"base": 30.00,  "per_km": 3.50, "stop": 15.00},
                    "SUV 1-7":      {"base": 55.00,  "per_km": 5.50, "stop": 25.00},
                    "Stretch 1-13": {"base": 135.00, "per_km": 9.50, "stop": 65.00},
                }
                conf = rates.get(service_type, rates["Sedan 1-5"])

                subtotal = conf["base"] + (distance_km * conf["per_km"])
                if extra_stop:    subtotal += conf["stop"]
                if has_tolls:     subtotal += 18.50
                if has_baby_seat: subtotal += 20.00

                final_price = subtotal * 2 if is_return_ride else subtotal
                final_price = round(final_price, 2)

                breakdown = {
                    "base":                  conf["base"],
                    "distance_km":           distance_km,
                    "distance_cost":         round(distance_km * conf["per_km"], 2),
                    "stop_cost":             conf["stop"] if extra_stop else 0,
                    "toll_cost":             18.50 if has_tolls else 0,
                    "baby_cost":             20.00 if has_baby_seat else 0,
                    "return_multiplier":     is_return_ride,
                    "subtotal_before_return": round(subtotal, 2),
                }

                # Stash price in session — never in a hidden form field
                request.session["pending_price"]     = final_price
                request.session["pending_breakdown"] = breakdown
                request.session["pending_has_tolls"] = has_tolls

                return render(request, "orders/booking_summary_preview.html", {
                    "step":        "confirm",
                    "form_data":   form_data,
                    "final_price": final_price,
                    "breakdown":   breakdown,
                    "has_tolls":   has_tolls,
                    "distance_km": distance_km,
                })

            except ValueError as e:
                return render(request, "bookings/booking_form.html", {
                    "error":     str(e),
                    "form_data": form_data,
                })
            except requests.RequestException:
                return render(request, "bookings/booking_form.html", {
                    "error":     "Could not connect to the routing service. Please check your addresses and try again.",
                    "form_data": form_data,
                })

        # ── STEP 2: Confirm — read from session, save Order ───────────────
        elif action == "confirm":
            final_price = request.session.pop("pending_price", None)

            if final_price is None:
                return render(request, "bookings/booking_form.html", {
                    "error":     "Your session expired. Please fill in the form again.",
                    "form_data": form_data,
                })

            try:
                new_order = Bookings.objects.create(
                    passenger_name=form_data["passenger_name"],
                    passenger_number=form_data["passenger_number"],
                    passenger_email=form_data["passenger_email"],
                    number_of_passengers=form_data["number_of_passengers"],
                    number_of_bags=form_data["number_of_bags"],
                    pickup_address=pickup,
                    destination_address=destination,
                    additional_stop=extra_stop,
                    flight_number=form_data["flight_number"],
                    pickup_date=form_data["pickup_date"],
                    pickup_time=form_data["pickup_time"] or datetime.time(0, 0),
                    limo_service_type=service_type,
                    baby_seat=has_baby_seat,
                    return_ride=is_return_ride,
                    special_instruction=form_data["special_instruction"],
                    vehicle_colour=form_data["vehicle_colour"],
                    wedding_ribbon=form_data["wedding_ribbon"],
                    special_signboard=form_data["special_signboard"],
                    name_on_card=form_data["name_on_card"],
                    card_type=form_data["card_type"],
                    card_number=form_data["card_number"],
                    total_price=final_price,
                )

                breakdown = request.session.pop("pending_breakdown", {})
                has_tolls  = request.session.pop("pending_has_tolls", False)

                return render(request, "orders/booking_confirmed.html", {
                    "order":     new_order,
                    "breakdown": breakdown,
                    "has_tolls": has_tolls,
                    "is_return": is_return_ride,
                })

            except Exception as e:
                return render(request, "bookings/booking_form.html", {
                    "error":     f"Could not save your booking: {str(e)}",
                    "form_data": form_data,
                })

    # ── GET ───────────────────────────────────────────────────────────────
    return render(request, "bookings/booking_form.html")
