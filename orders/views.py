import datetime
import logging
import requests
import stripe
import googlemaps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Order

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Service type configuration
# ─────────────────────────────────────────────────────────────────────────────

MELBOURNE_AIRPORT = "Melbourne Airport (Tullamarine), Departure Dr, Tullamarine VIC 3043"

SERVICE_TYPES = {
    # ?type=ptp  — Point to Point
    "ptp":  {
        "label": "Point to Point",
        "show_destination": True,
        "show_flight": False,
        "lock_pickup": None,
        "lock_destination": None,
        "flat": False,
    },
    # ?type=oh   — 1 Hour / As Directed  ($100 flat, +$25 next tier)
    "oh":   {
        "label": "1 Hour / As Directed",
        "show_destination": False,
        "show_flight": False,
        "lock_pickup": None,
        "lock_destination": None,
        "flat": True,
    },
    # ?type=th   — 2 Hour Hire  ($200 flat, 2.5% discount, +$50 next tier)
    "th":   {
        "label": "2 Hour Hire",
        "show_destination": False,
        "show_flight": False,
        "lock_pickup": None,
        "lock_destination": None,
        "flat": True,
    },
    # ?type=fair — From Airport  (pickup locked = airport, show flight number)
    "fair": {
        "label": "From Airport",
        "show_destination": True,
        "show_flight": True,
        "lock_pickup": MELBOURNE_AIRPORT,
        "lock_destination": None,
        "flat": False,
    },
    # ?type=tair — To Airport  (destination locked = airport, show flight number)
    "tair": {
        "label": "To Airport",
        "show_destination": True,
        "show_flight": True,
        "lock_pickup": None,
        "lock_destination": MELBOURNE_AIRPORT,
        "flat": False,
    },
}

# ── Flat rates ────────────────────────────────────────────────────────────────
# th  = 2 Hour Hire:  Sedan $200, SUV $250 (+$50), Stretch $300 (+$50)  | 2.5% discount
# oh  = 1 Hour Hire:  Sedan $100, SUV $125 (+$25), Stretch $150 (+$25)  | no discount

TH_RATES = {
    "Sedan 1-5":    200.00,
    "SUV 1-7":      250.00,
    "Stretch 1-13": 300.00,
}
TH_DISCOUNT = 0.025  # 2.5%

OH_RATES = {
    "Sedan 1-5":    100.00,
    "SUV 1-7":      125.00,
    "Stretch 1-13": 150.00,
}

# ── Per-km rates (ptp / fair / tair) ─────────────────────────────────────────
RATES = {
    "Sedan 1-5":    {"base": 30.00,  "per_km": 3.50, "stop": 15.00},
    "SUV 1-7":      {"base": 55.00,  "per_km": 5.50, "stop": 25.00},
    "Stretch 1-13": {"base": 135.00, "per_km": 9.50, "stop": 65.00},
}

RETURN_DISCOUNT = 0.05  # 5% for return rides on per-km types


# ─────────────────────────────────────────────────────────────────────────────
# Helper 1 – Distance via OSRM + Nominatim
# ─────────────────────────────────────────────────────────────────────────────

# def calculate_distance(pickup: str, destination: str, extra_stop: str | None) -> dict:
#     """
#     Uses Google Maps Directions API to calculate driving distance.
#     Returns distance_km and has_tolls.
#     """
#     gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
# 
#     waypoints = [extra_stop] if extra_stop else None
# 
#     directions = gmaps.directions(
#         origin=pickup,
#         destination=destination,
#         waypoints=waypoints,
#         mode="driving",
#         optimize_waypoints=False,
#     )
# 
#     if not directions:
#         raise ValueError("Google Maps returned no route for the given addresses.")
# 
#     total_meters = sum(leg["distance"]["value"] for leg in directions[0]["legs"])
#     distance_km  = round(total_meters / 1000, 2)
# 
#     has_tolls = any(
#         "toll" in step.get("html_instructions", "").lower()
#         for leg in directions[0]["legs"]
#         for step in leg["steps"]
#     )
# 
#     return {
#         "distance_km": distance_km,
#         "has_tolls":   has_tolls,
#     }

def calculate_distance(pickup: str, destination: str, extra_stop: str | None) -> dict:
    def geocode(address):
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1}
        headers = {"User-Agent": "LimoBookingApp/1.0"}
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        if not data:
            raise ValueError(f"Could not find address: {address}")
        return f"{data[0]['lon']},{data[0]['lat']}"

    try:
        loc1 = geocode(pickup)
        loc2 = geocode(destination)
        coords = f"{loc1};{loc2}"

        if extra_stop:
            loc_extra = geocode(extra_stop)
            coords = f"{loc1};{loc_extra};{loc2}"

        route_url = f"https://router.project-osrm.org/route/v1/driving/{coords}"
        route_resp = requests.get(route_url, params={"overview": "false"}).json()

        if route_resp.get("code") != "Ok":
            raise ValueError("OSRM could not calculate a route.")

        total_meters = route_resp["routes"][0]["distance"]
        distance_km = round(total_meters / 1000, 2)

        return {"distance_km": distance_km, "has_tolls": True}

    except Exception as e:
        logger.error(f"Routing error: {e}")
        raise ValueError(f"Route calculation failed: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Helper 2 – Pricing
# ─────────────────────────────────────────────────────────────────────────────

def calculate_price(
    service_type_key: str,
    distance_km:      float,
    has_tolls:        bool,
    vehicle:          str,
    extra_stop:       str | None,
    has_baby_seat:    bool,
    is_return_ride:   bool,
) -> dict:

    # ── th: 2 Hour Hire flat rate with 2.5% discount ─────────────────────────
    if service_type_key == "th":
        flat      = TH_RATES.get(vehicle, 200.00)
        baby_cost = 20.00 if has_baby_seat else 0
        subtotal  = flat + baby_cost
        discount  = round(subtotal * TH_DISCOUNT, 2)
        total     = round(subtotal - discount, 2)
        return {
            "service_type_key":       "th",
            "base":                   flat,
            "distance_km":            0,
            "distance_cost":          0,
            "stop_cost":              0,
            "toll_cost":              0,
            "baby_cost":              baby_cost,
            "subtotal_before_return": subtotal,
            "return_multiplier":      False,
            "return_discount":        discount,
            "discount_label":         "2.5% hire discount",
            "final_price":            total,
            "final_price_cents":      int(total * 100),
        }

    # ── oh: 1 Hour / As Directed flat rate, no discount ──────────────────────
    if service_type_key == "oh":
        flat      = OH_RATES.get(vehicle, 100.00)
        baby_cost = 20.00 if has_baby_seat else 0
        total     = round(flat + baby_cost, 2)
        return {
            "service_type_key":       "oh",
            "base":                   flat,
            "distance_km":            0,
            "distance_cost":          0,
            "stop_cost":              0,
            "toll_cost":              0,
            "baby_cost":              baby_cost,
            "subtotal_before_return": total,
            "return_multiplier":      False,
            "return_discount":        0,
            "discount_label":         "",
            "final_price":            total,
            "final_price_cents":      int(total * 100),
        }

    # ── Per-km pricing (ptp / fair / tair) ────────────────────────────────────
    conf     = RATES.get(vehicle, RATES["Sedan 1-5"])
    subtotal = conf["base"] + (distance_km * conf["per_km"])
    if extra_stop:    subtotal += conf["stop"]
    if has_tolls:     subtotal += 18.50
    if has_baby_seat: subtotal += 20.00

    if is_return_ride:
        return_total    = subtotal * 2
        discount_amount = round(return_total * RETURN_DISCOUNT, 2)
        final_price     = round(return_total - discount_amount, 2)
    else:
        discount_amount = 0.00
        final_price     = round(subtotal, 2)

    return {
        "service_type_key":       service_type_key,
        "base":                   conf["base"],
        "distance_km":            distance_km,
        "distance_cost":          round(distance_km * conf["per_km"], 2),
        "stop_cost":              conf["stop"] if extra_stop else 0,
        "toll_cost":              18.50 if has_tolls else 0,
        "baby_cost":              20.00 if has_baby_seat else 0,
        "subtotal_before_return": round(subtotal, 2),
        "return_multiplier":      is_return_ride,
        "return_discount":        discount_amount,
        "discount_label":         "5% return discount" if is_return_ride else "",
        "final_price":            final_price,
        "final_price_cents":      int(final_price * 100),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Booking view
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_type(request):
    """Pull ?type= from GET or hidden field from POST, default ptp."""
    raw = request.GET.get("type", request.POST.get("service_type_key", "ptp")).lower().strip()
    return raw if raw in SERVICE_TYPES else "ptp"


@login_required
def orders(request):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    type_key = _resolve_type(request)
    svc      = SERVICE_TYPES[type_key]

    # ── POST ─────────────────────────────────────────────────────────────
    if request.method == "POST":
        action = request.POST.get("action", "calculate")

        pickup      = svc["lock_pickup"]      or request.POST.get("pickup_address", "").strip()
        destination = svc["lock_destination"] or request.POST.get("destination_address", "").strip()

        # Flat-rate types have no fixed destination
        if type_key in ("th", "oh"):
            destination = f"{svc['label']} — Open Route"

        extra_stop     = request.POST.get("additional_stop", "").strip() or None
        vehicle        = request.POST.get("limo_service_type", "Sedan 1-5")
        has_baby_seat  = "baby_seat"   in request.POST
        is_return_ride = "return_ride" in request.POST and type_key not in ("th", "oh")
        flight_number  = request.POST.get("flight_number", "") if svc["show_flight"] else ""

        form_data = {
            "service_type_key":     type_key,
            "service_type_label":   svc["label"],
            "passenger_name":       request.POST.get("passenger_name", ""),
            "passenger_number":     request.POST.get("passenger_number", ""),
            "passenger_email":      request.POST.get("passenger_email", ""),
            "number_of_passengers": request.POST.get("number_of_passengers", 2),
            "number_of_bags":       request.POST.get("number_of_bags", 2),
            "pickup_address":       pickup,
            "destination_address":  destination,
            "additional_stop":      extra_stop or "",
            "flight_number":        flight_number,
            "pickup_date":          request.POST.get("pickup_date", str(datetime.date.today())),
            "pickup_time":          request.POST.get("pickup_time", ""),
            "limo_service_type":    vehicle,
            "baby_seat":            has_baby_seat,
            "return_ride":          is_return_ride,
            "special_instruction":  request.POST.get("special_instruction", ""),
            "vehicle_colour":       request.POST.get("vehicle_colour", ""),
            "wedding_ribbon":       request.POST.get("wedding_ribbon", ""),
            "special_signboard":    request.POST.get("special_signboard", ""),
            # UI flags
            "show_destination":     svc["show_destination"],
            "show_flight":          svc["show_flight"],
            "lock_pickup":          svc["lock_pickup"],
            "lock_destination":     svc["lock_destination"],
            "is_flat":              svc["flat"],
        }

        def form_error(msg):
            return render(request, "orders/booking_form.html", {
                "error": msg, "form_data": form_data, "svc": svc, "type_key": type_key,
                "google_maps_key": settings.GOOGLE_MAPS_API_KEY,
            })

        # ── Calculate ─────────────────────────────────────────────────────
        if action == "calculate":
            try:
                if type_key in ("th", "oh"):
                    route = {"distance_km": 0, "has_tolls": False}
                else:
                    if not pickup or not destination:
                        return form_error("Please enter both pickup and destination addresses.")
                    route = calculate_distance(pickup, destination, extra_stop)

                breakdown = calculate_price(
                    service_type_key=type_key,
                    distance_km=route["distance_km"],
                    has_tolls=route["has_tolls"],
                    vehicle=vehicle,
                    extra_stop=extra_stop,
                    has_baby_seat=has_baby_seat,
                    is_return_ride=is_return_ride,
                )

                request.session["pending_price"]     = breakdown["final_price"]
                request.session["pending_breakdown"] = breakdown
                request.session["pending_has_tolls"] = route["has_tolls"]

                return render(request, "orders/booking_summary_preview.html", {
                    "form_data":   form_data,
                    "final_price": breakdown["final_price"],
                    "breakdown":   breakdown,
                    "has_tolls":   route["has_tolls"],
                    "svc":         svc,
                    "type_key":    type_key,
                })

            except Exception as exc:
                return form_error(f"Route calculation failed: {exc}")

        # ── Confirm → create Order → redirect to Stripe Checkout ─────────
        elif action == "confirm":
            final_price = request.session.get("pending_price")
            if final_price is None:
                return form_error("Your session expired. Please recalculate the price.")

            breakdown = request.session.get("pending_breakdown", {})
            has_tolls = request.session.get("pending_has_tolls", False)

            try:
                order = Order.objects.create(
                    user=request.user,
                    service_type=type_key,
                    passenger_name=form_data["passenger_name"],
                    passenger_number=form_data["passenger_number"],
                    passenger_email=form_data["passenger_email"],
                    number_of_passengers=form_data["number_of_passengers"],
                    number_of_bags=form_data["number_of_bags"],
                    pickup_address=pickup,
                    destination_address=destination,
                    additional_stop=extra_stop,
                    flight_number=flight_number,
                    pickup_date=form_data["pickup_date"],
                    pickup_time=form_data["pickup_time"] or datetime.time(0, 0),
                    limo_service_type=vehicle,
                    baby_seat=has_baby_seat,
                    return_ride=is_return_ride,
                    special_instruction=form_data["special_instruction"],
                    vehicle_colour=form_data["vehicle_colour"],
                    wedding_ribbon=form_data["wedding_ribbon"],
                    special_signboard=form_data["special_signboard"],
                    total_price=final_price,
                    paid=False,
                )
            except Exception as exc:
                return form_error(f"Could not save your booking: {exc}")

            # Build absolute success/cancel URLs.
            # IMPORTANT: build the base URL first, then append the Stripe
            # template variable as a plain string AFTER build_absolute_uri()
            # so Django never percent-encodes the curly braces.
            base_status_url = request.build_absolute_uri(
                reverse("status", args=[order.id])
            )
            success_url = base_status_url + "?session_id={CHECKOUT_SESSION_ID}"
            cancel_url  = base_status_url

            try:
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    mode="payment",
                    line_items=[{
                        "price_data": {
                            "currency": "aud",
                            "unit_amount": int(final_price * 100),
                            "product_data": {
                                "name": f"{svc['label']} — Melbourne Chauffeur",
                                "description": (
                                    f"{pickup} → {destination} on {form_data['pickup_date']}"
                                    if type_key not in ("th", "oh")
                                    else f"{svc['label']} from {pickup} on {form_data['pickup_date']}"
                                ),
                            },
                        },
                        "quantity": 1,
                    }],
                    customer_email=form_data["passenger_email"] or None,
                    success_url=success_url,
                    cancel_url=cancel_url,
                    metadata={
                        "order_id":     order.id,
                        "service_type": type_key,
                        "passenger":    form_data["passenger_name"],
                        "pickup":       pickup,
                        "dropoff":      destination,
                        "pickup_date":  form_data["pickup_date"],
                    },
                )

                order.stripe_payment_intent_id = session.id
                order.save(update_fields=["stripe_payment_intent_id"])

                for k in ("pending_price", "pending_breakdown", "pending_has_tolls"):
                    request.session.pop(k, None)

                # Redirect the user to Stripe Checkout
                return HttpResponseRedirect(session.url)

            except stripe.error.StripeError as exc:
                order.delete()
                return form_error(f"Payment setup failed: {exc.user_message}")

    # ── GET ───────────────────────────────────────────────────────────────
    # Pre-fill email and phone from user profile
    prefill_email = request.user.email or ""
    prefill_phone = ""
    try:
        prefill_phone = request.user.extended_profile.phone or ""
    except AttributeError:
        pass

    form_data = {
        "service_type_key":     type_key,
        "service_type_label":   svc["label"],
        "pickup_address":       svc["lock_pickup"]      or "",
        "destination_address":  svc["lock_destination"] or "",
        "pickup_date":          str(datetime.date.today()),
        "show_destination":     svc["show_destination"],
        "show_flight":          svc["show_flight"],
        "lock_pickup":          svc["lock_pickup"],
        "lock_destination":     svc["lock_destination"],
        "is_flat":              svc["flat"],
        "number_of_passengers": 2,
        "number_of_bags":       2,
        "passenger_email":      prefill_email,
        "passenger_number":     prefill_phone,
    }
    return render(request, "orders/booking_form.html", {
        "form_data":       form_data,
        "svc":             svc,
        "type_key":        type_key,
        "google_maps_key": settings.GOOGLE_MAPS_API_KEY,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Order status  — Stripe redirects here after Checkout
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    # Stripe appends ?session_id=... on success redirect — verify it
    session_id = request.GET.get("session_id")
    if session_id and not order.paid:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid":
                Order.objects.filter(id=order.id, paid=False).update(paid=True)
                order.refresh_from_db()
        except stripe.error.StripeError as exc:
            logger.warning("Could not verify Stripe session %s: %s", session_id, exc)

    template = "orders/booking_confirmed.html" if order.paid else "orders/booking_cancelled.html"
    return render(request, template, {"order": order})


# ─────────────────────────────────────────────────────────────────────────────
# Stripe webhook — server-side confirmation (belt & braces)
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def stripe_webhook(request):
    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.META.get("HTTP_STRIPE_SIGNATURE", ""),
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        logger.warning("Stripe webhook signature failed: %s", exc)
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        session  = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        if order_id and session.get("payment_status") == "paid":
            updated = Order.objects.filter(
                id=order_id, paid=False
            ).update(paid=True)
            if updated:
                logger.info("Order #%s marked paid via webhook.", order_id)

    elif event["type"] == "checkout.session.expired":
        order_id = event["data"]["object"].get("metadata", {}).get("order_id")
        if order_id:
            logger.warning("Checkout session expired for order #%s", order_id)

    return HttpResponse(status=200)
