from django.shortcuts import render, redirect
from .models import ContactRequest, FAQ
from django.contrib import messages

# Create your views here.


def home(request):
    
    faq = FAQ.objects.all()
    
    context = {
        'faq':faq,
    }
    return render(request, 'core/index.html', context)


def contact(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        what_said = request.POST.get('what_said')
        
        try:
            contact_request = ContactRequest.objects.create(email=email, what_said=what_said)
            messages.success(request, "Thank you — we'll be in touch within the hour.")
            return redirect('contact')
            
        except Exception as e:
            messages.error(request, "Something went wrong. Please try again.")

        
    return render(request, 'core/contact.html')


def terms(request):
    return render(request, 'core/terms.html')

def about_us(request):
    return render(request, 'core/about.html')

def privacy_policy(request):
    return render(request, 'core/privacy_ policy.html')