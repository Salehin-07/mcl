from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, authenticate
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from .models import ExtendedProfile

# Create your views here.
def user_login(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        password   = request.POST.get('password', '')
        next_url   = request.POST.get('next', '')

        if not identifier or not password:
            messages.error(request, 'Please enter your email or phone and password.')
            return render(request, 'accounts/login.html', {'identifier': identifier, 'next': next_url})

        # ── Resolve identifier to a username ─────────────────
        username = None

        if '@' in identifier:
            # treat as email
            try:
                user = User.objects.get(email__iexact=identifier)
                username = user.username
            except User.DoesNotExist:
                username = None
        else:
            # treat as phone — look up via ExtendedProfile
            try:
                profile  = ExtendedProfile.objects.get(phone=identifier)
                username = profile.user.username
            except ExtendedProfile.DoesNotExist:
                username = None

        # ── Authenticate ──────────────────────────────────────
        user = authenticate(request, username=username, password=password) if username else None

        if user is not None:
            login(request, user)
            return redirect(next_url or 'home')
        else:
            messages.error(request, 'No account found with those details. Please check and try again.')
            return render(request, 'accounts/login.html', {'identifier': identifier, 'next': next_url})

    return render(request, 'accounts/login.html', {'next': request.GET.get('next', '')})

def signup(request):
    if request.user.is_authenticated:
        return redirect('home')
        
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip().lower()
        phone      = request.POST.get('phone', '').strip()
        password1  = request.POST.get('password1', '')
        password2  = request.POST.get('password2', '')

        # ── Validation ──────────────────────────────────────
        if not all([first_name, last_name, email, phone, password1, password2]):
            messages.error(request, 'All fields are required.')
            return render(request, 'accounts/signup.html')

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'accounts/signup.html')

        if len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'accounts/signup.html')

        # ── Duplicate checks ─────────────────────────────────
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'An account with this email address already exists.')
            return render(request, 'accounts/signup.html')

        if ExtendedProfile.objects.filter(phone=phone).exists():
            messages.error(request, 'An account with this phone number already exists.')
            return render(request, 'accounts/signup.html')

        # ── Create user + profile ────────────────────────────
        try:
            user = User.objects.create_user(
                username   = email,
                email      = email,
                password   = password1,
                first_name = first_name,
                last_name  = last_name,
            )
            ExtendedProfile.objects.create(user=user, phone=phone)

            login(request, user)
            messages.success(request, f'Welcome, {first_name}! Your account has been created.')
            return redirect('home')

        except Exception as e:
            print(str(e))
            messages.error(request, 'Something went wrong. Please try again.')
            return render(request, 'accounts/signup.html')

    return render(request, 'accounts/signup.html')

@login_required
def profile(request):
    return render(request, 'accounts/profile.html')


@login_required
def profile_update_details(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()

        if not all([first_name, last_name, email, phone]):
            messages.error(request, 'All fields are required.')
            return redirect('profile')

        # check email not taken by someone else
        if User.objects.filter(email__iexact=email).exclude(pk=request.user.pk).exists():
            messages.error(request, 'That email address is already in use.')
            return redirect('profile')

        # check phone not taken by someone else
        
        if ExtendedProfile.objects.filter(phone=phone).exclude(user=request.user).exists():
            messages.error(request, 'That phone number is already in use.')
            return redirect('profile')

        request.user.first_name = first_name
        request.user.last_name  = last_name
        request.user.email      = email
        request.user.username   = email   # keep username in sync
        request.user.save()

        request.user.extended_profile.phone = phone
        request.user.extended_profile.save()

        messages.success(request, 'Your details have been updated.')
    return redirect('profile')


@login_required
def profile_update_password(request):
    if request.method == 'POST':
        current  = request.POST.get('current_password', '')
        new_pw   = request.POST.get('new_password', '')
        confirm  = request.POST.get('confirm_password', '')

        if not request.user.check_password(current):
            messages.error(request, 'Your current password is incorrect.')
            return redirect('profile?tab=password')

        if len(new_pw) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
            return redirect('profile')

        if new_pw != confirm:
            messages.error(request, 'New passwords do not match.')
            return redirect('profile')

        request.user.set_password(new_pw)
        request.user.save()
        update_session_auth_hash(request, request.user)  # keeps user logged in
        messages.success(request, 'Password updated successfully.')
    return redirect('profile')


@login_required
def profile_delete(request):
    if request.method == 'POST':
        request.user.delete()
        messages.success(request, 'Your account has been deleted.')
        return redirect('home')
    return redirect('profile')