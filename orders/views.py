import googlemaps
from django.conf import settings
from django.shortcuts import render
from .models import Order
import datetime


def orders(request):
    """
    Two-step booking flow:

    GET  → Show the blank booking form (booking_form.html)

    POST action=calculate →
        Validate, call Google Maps, compute price.
        Re-render booking_form.html with price context so the user
        sees the summary panel and a "Confirm Booking" button.
        All form data is echoed back as hidden fields — no DB write yet.

    POST action=confirm →
        All data + pre-computed price come back as hidden fields.
        We trust the price we calculated in the previous step (stored
        in session so it cannot be tampered with from the browser).
        Save the Order to the database and render booking_summary.html.
    """

    if request.method == 'POST':
        action = request.POST.get('action', 'calculate')

        # ── Shared: extract all form fields ──────────────────────────────
        pickup       = request.POST.get('pickup_address', '').strip()
        destination  = request.POST.get('destination_address', '').strip()
        extra_stop   = request.POST.get('additional_stop', '').strip() or None
        service_type = request.POST.get('limo_service_type', 'Sedan 1-5')
        has_baby_seat  = 'baby_seat'    in request.POST
        is_return_ride = 'return_ride'  in request.POST

        # Collect everything we'll need to echo back to the template
        form_data = {
            'passenger_name':      request.POST.get('passenger_name', ''),
            'passenger_number':    request.POST.get('passenger_number', ''),
            'passenger_email':     request.POST.get('passenger_email', ''),
            'number_of_passengers': request.POST.get('number_of_passengers', 2),
            'number_of_bags':      request.POST.get('number_of_bags', 2),
            'pickup_address':      pickup,
            'destination_address': destination,
            'additional_stop':     extra_stop or '',
            'flight_number':       request.POST.get('flight_number', ''),
            'pickup_date':         request.POST.get('pickup_date', str(datetime.date.today())),
            'pickup_time':         request.POST.get('pickup_time', ''),
            'limo_service_type':   service_type,
            'baby_seat':           has_baby_seat,
            'return_ride':         is_return_ride,
            'special_instruction': request.POST.get('special_instruction', ''),
            'vehicle_colour':      request.POST.get('vehicle_colour', ''),
            'wedding_ribbon':      request.POST.get('wedding_ribbon', ''),
            'special_signboard':   request.POST.get('special_signboard', ''),
            'name_on_card':        request.POST.get('name_on_card', ''),
            'card_type':           request.POST.get('card_type', ''),
            'card_number':         request.POST.get('card_number', ''),
        }

        # ── STEP 1: Calculate price, show summary, do NOT save ────────────
        if action == 'calculate':
            gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)

            try:
                waypoints = [extra_stop] if extra_stop else None

                directions = gmaps.directions(
                    origin=pickup,
                    destination=destination,
                    waypoints=waypoints,
                    mode="driving",
                    optimize_waypoints=True,
                )

                total_meters = sum(
                    leg['distance']['value']
                    for leg in directions[0]['legs']
                )
                distance_km = round(total_meters / 1000, 2)

                has_tolls = any(
                    "Toll road" in step.get('html_instructions', '')
                    for leg in directions[0]['legs']
                    for step in leg['steps']
                )

                rates = {
                    'Sedan 1-5':    {'base': 30.00,  'per_km': 3.50, 'stop': 15.00},
                    'SUV 1-7':      {'base': 55.00,  'per_km': 5.50, 'stop': 25.00},
                    'Stretch 1-13': {'base': 135.00, 'per_km': 9.50, 'stop': 65.00},
                }
                conf = rates.get(service_type, rates['Sedan 1-5'])

                subtotal = conf['base'] + (distance_km * conf['per_km'])
                if extra_stop:    subtotal += conf['stop']
                if has_tolls:     subtotal += 18.50
                if has_baby_seat: subtotal += 20.00

                final_price = subtotal * 2 if is_return_ride else subtotal
                final_price = round(final_price, 2)

                # Break down for display
                breakdown = {
                    'base':         conf['base'],
                    'distance_km':  distance_km,
                    'distance_cost': round(distance_km * conf['per_km'], 2),
                    'stop_cost':    conf['stop'] if extra_stop else 0,
                    'toll_cost':    18.50 if has_tolls else 0,
                    'baby_cost':    20.00 if has_baby_seat else 0,
                    'return_multiplier': is_return_ride,
                    'subtotal_before_return': round(subtotal, 2),
                }

                # Store price in session so the confirm step cannot be spoofed
                request.session['pending_price']     = final_price
                request.session['pending_breakdown'] = breakdown
                request.session['pending_has_tolls'] = has_tolls

                context = {
                    'step':        'confirm',        # tells template to show summary page
                    'form_data':   form_data,
                    'final_price': final_price,
                    'breakdown':   breakdown,
                    'has_tolls':   has_tolls,
                    'distance_km': distance_km,
                }
                return render(request, 'orders/booking_summary_preview.html', context)

            except Exception as e:
                return render(request, 'orders/booking_form.html', {
                    'error': f"Route calculation failed: {str(e)}",
                    'form_data': form_data,
                })

        # ── STEP 2: Confirm — read price from session, save Order ─────────
        elif action == 'confirm':
            final_price = request.session.pop('pending_price', None)

            if final_price is None:
                # Session expired or direct POST — reject gracefully
                return render(request, 'orders/booking_form.html', {
                    'error': "Your session expired. Please recalculate the price.",
                    'form_data': form_data,
                })

            try:
                new_order = Order.objects.create(
                    passenger_name=form_data['passenger_name'],
                    passenger_number=form_data['passenger_number'],
                    passenger_email=form_data['passenger_email'],
                    number_of_passengers=form_data['number_of_passengers'],
                    number_of_bags=form_data['number_of_bags'],
                    pickup_address=pickup,
                    destination_address=destination,
                    additional_stop=extra_stop,
                    flight_number=form_data['flight_number'],
                    pickup_date=form_data['pickup_date'],
                    pickup_time=form_data['pickup_time'] or datetime.time(0, 0),
                    limo_service_type=service_type,
                    baby_seat=has_baby_seat,
                    return_ride=is_return_ride,
                    special_instruction=form_data['special_instruction'],
                    vehicle_colour=form_data['vehicle_colour'],
                    wedding_ribbon=form_data['wedding_ribbon'],
                    special_signboard=form_data['special_signboard'],
                    name_on_card=form_data['name_on_card'],
                    card_type=form_data['card_type'],
                    card_number=form_data['card_number'],
                    total_price=final_price,
                )

                breakdown = request.session.pop('pending_breakdown', {})
                has_tolls  = request.session.pop('pending_has_tolls', False)

                return render(request, 'orders/booking_confirmed.html', {
                    'order':       new_order,
                    'breakdown':   breakdown,
                    'has_tolls':   has_tolls,
                    'is_return':   is_return_ride,
                })

            except Exception as e:
                return render(request, 'orders/booking_form.html', {
                    'error': f"Could not save your booking: {str(e)}",
                    'form_data': form_data,
                })

    # ── GET ───────────────────────────────────────────────────────────────
    return render(request, 'orders/booking_form.html')
