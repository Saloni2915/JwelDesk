from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from inventory.models import Category, JewelleryItem
from customers.models import Customer
from sales.models import Sale, Enquiry


class Command(BaseCommand):
    help = 'Seeds initial jewellery categories, sample items, customers, enquiries, and sales.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.NOTICE('Seeding database with initial jewellery data...'))

        # Ensure admin user exists
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@jeweldesk.com', 'admin123')
            self.stdout.write(self.style.SUCCESS("Created superuser 'admin' with password 'admin123'."))

        # 1. Categories
        categories_data = [
            ('Rings', 'Engagement rings, wedding bands, solitaire rings, and daily wear rings.'),
            ('Necklaces', 'Bridal necklaces, chokers, temple jewellery, and antique necklaces.'),
            ('Earrings', 'Studs, jhumkas, drops, chandeliers, and hoops.'),
            ('Bangles & Bracelets', 'Traditional gold bangles, kadas, and diamond bracelets.'),
            ('Chains', 'Gold, silver, and platinum chains of various purities and links.'),
            ('Pendants', 'Religious pendants, solitaires, and designer locket pendants.'),
            ('Mangalsutra', 'Traditional Maharashtrian, North Indian, and modern lightweight mangalsutras.'),
            ('Coins & Bars', '24K (999) gold and silver coins and minted bars.'),
            ('Anklets', 'Silver and gold anklets (payal) and toe rings.'),
        ]

        categories = {}
        for name, desc in categories_data:
            cat, created = Category.objects.get_or_create(
                name=name,
                defaults={'description': desc}
            )
            categories[name] = cat
            if created:
                self.stdout.write(f"  + Created Category: {name}")

        # 2. Customers
        customers_data = [
            ('Rajesh Sharma', '+91 9876543210', 'rajesh.sharma@example.com', '102, Shanti Heights, Andheri West, Mumbai, MH'),
            ('Priya Patel', '+91 9823456789', 'priya.patel@example.com', '45, Navrangpura, Ahmedabad, GJ'),
            ('Ananya Desai', '+91 9811122233', 'ananya.desai@example.com', 'Flat 4B, Koregaon Park, Pune, MH'),
            ('Vikram Singh', '+91 9899001122', 'vikram.singh@example.com', 'Sector 15, Rohini, New Delhi, DL'),
            ('Meera Joshi', '+91 9845012345', 'meera.joshi@example.com', '12, Indiranagar, Bengaluru, KA'),
        ]

        customers = {}
        for name, mobile, email, addr in customers_data:
            cust, created = Customer.objects.get_or_create(
                mobile=mobile,
                defaults={'name': name, 'email': email, 'address': addr}
            )
            customers[name] = cust
            if created:
                self.stdout.write(f"  + Created Customer: {name}")

        # 3. Jewellery Items (Demonstrating multiple physical pieces with shared design codes)
        items_data = [
            {
                'item_code': 'GLD-RN-001',
                'design_code': 'DSN-RN-001',
                'name': '22K Gold Solitaire Floral Ring (Piece 1)',
                'category': categories['Rings'],
                'metal_type': 'Gold',
                'purity': '22K (916 Hallmarked)',
                'gross_weight': Decimal('5.500'),
                'net_weight': Decimal('5.200'),
                'making_charge': Decimal('2500.00'),
                'selling_price': Decimal('48500.00'),
                'status': 'Available',
            },
            {
                'item_code': 'GLD-RN-001-B',
                'design_code': 'DSN-RN-001',
                'name': '22K Gold Solitaire Floral Ring (Piece 2)',
                'category': categories['Rings'],
                'metal_type': 'Gold',
                'purity': '22K (916 Hallmarked)',
                'gross_weight': Decimal('5.650'),
                'net_weight': Decimal('5.350'),
                'making_charge': Decimal('2500.00'),
                'selling_price': Decimal('49800.00'),
                'status': 'Available',
            },
            {
                'item_code': 'DIA-ER-002',
                'design_code': 'DSN-ER-002',
                'name': '18K Diamond Solitaire Studs (0.50ct VVS)',
                'category': categories['Earrings'],
                'metal_type': 'Diamond',
                'purity': '18K (750) / VVS-1 GH',
                'gross_weight': Decimal('4.200'),
                'net_weight': Decimal('3.800'),
                'making_charge': Decimal('4500.00'),
                'selling_price': Decimal('68000.00'),
                'status': 'Available',
            },
            {
                'item_code': 'DIA-ER-002-B',
                'design_code': 'DSN-ER-002',
                'name': '18K Diamond Solitaire Studs (0.50ct VVS - Piece 2)',
                'category': categories['Earrings'],
                'metal_type': 'Diamond',
                'purity': '18K (750) / VVS-1 GH',
                'gross_weight': Decimal('4.100'),
                'net_weight': Decimal('3.700'),
                'making_charge': Decimal('4500.00'),
                'selling_price': Decimal('66500.00'),
                'status': 'Available',
            },
            {
                'item_code': 'GLD-NK-003',
                'design_code': 'DSN-NK-003',
                'name': 'Royal Antique Temple Gold Necklace',
                'category': categories['Necklaces'],
                'metal_type': 'Gold',
                'purity': '22K (916 Hallmarked)',
                'gross_weight': Decimal('45.000'),
                'net_weight': Decimal('42.500'),
                'making_charge': Decimal('22000.00'),
                'selling_price': Decimal('345000.00'),
                'status': 'Available',
            },
            {
                'item_code': 'GLD-CN-004',
                'design_code': 'DSN-COIN-10G',
                'name': '24K Pure Gold Minted Coin (10 Grams)',
                'category': categories['Coins & Bars'],
                'metal_type': 'Gold',
                'purity': '24K (999 Purity)',
                'gross_weight': Decimal('10.000'),
                'net_weight': Decimal('10.000'),
                'making_charge': Decimal('800.00'),
                'selling_price': Decimal('78500.00'),
                'status': 'Available',
            },
            {
                'item_code': 'GLD-BG-005',
                'design_code': 'DSN-BG-005',
                'name': 'Traditional Filigree Gold Bangle Pair',
                'category': categories['Bangles & Bracelets'],
                'metal_type': 'Gold',
                'purity': '22K (916 Hallmarked)',
                'gross_weight': Decimal('32.000'),
                'net_weight': Decimal('32.000'),
                'making_charge': Decimal('14000.00'),
                'selling_price': Decimal('245000.00'),
                'status': 'Available',
            },
            {
                'item_code': 'SLV-AK-006',
                'design_code': 'DSN-AK-006',
                'name': 'Sterling Silver Handcrafted Payal (Anklet)',
                'category': categories['Anklets'],
                'metal_type': 'Silver',
                'purity': '925 Sterling Silver',
                'gross_weight': Decimal('48.000'),
                'net_weight': Decimal('48.000'),
                'making_charge': Decimal('1200.00'),
                'selling_price': Decimal('5600.00'),
                'status': 'Available',
            },
            {
                'item_code': 'PLT-BD-007',
                'design_code': 'DSN-PLT-007',
                'name': 'Platinum Love Bands with Accent Diamonds',
                'category': categories['Rings'],
                'metal_type': 'Platinum',
                'purity': 'Pt 950',
                'gross_weight': Decimal('11.500'),
                'net_weight': Decimal('11.200'),
                'making_charge': Decimal('7500.00'),
                'selling_price': Decimal('74000.00'),
                'status': 'Available',
            },
            {
                'item_code': 'GLD-MS-008',
                'design_code': 'DSN-MS-008',
                'name': 'Contemporary Diamond & Gold Mangalsutra',
                'category': categories['Mangalsutra'],
                'metal_type': 'Gold',
                'purity': '18K (750)',
                'gross_weight': Decimal('8.500'),
                'net_weight': Decimal('7.800'),
                'making_charge': Decimal('5000.00'),
                'selling_price': Decimal('62000.00'),
                'status': 'Available',
            },
            {
                'item_code': 'GLD-CH-009',
                'design_code': 'DSN-CH-009',
                'name': '22K Solid Rope Link Gold Chain',
                'category': categories['Chains'],
                'metal_type': 'Gold',
                'purity': '22K (916)',
                'gross_weight': Decimal('18.000'),
                'net_weight': Decimal('18.000'),
                'making_charge': Decimal('6500.00'),
                'selling_price': Decimal('138000.00'),
                'status': 'Available',
            },
            {
                'item_code': 'DIA-PD-010',
                'design_code': 'DSN-PD-010',
                'name': 'Tear Drop Diamond Pendant (0.35ct)',
                'category': categories['Pendants'],
                'metal_type': 'Diamond',
                'purity': '18K White Gold / VS-GH',
                'gross_weight': Decimal('3.100'),
                'net_weight': Decimal('2.900'),
                'making_charge': Decimal('3000.00'),
                'selling_price': Decimal('38000.00'),
                'status': 'Available',
            },
        ]

        items = {}
        for item_info in items_data:
            code = item_info['item_code']
            item, created = JewelleryItem.objects.get_or_create(
                item_code=code,
                defaults=item_info
            )
            items[code] = item
            if created:
                self.stdout.write(f"  + Created Jewellery Item: {code} - {item.name}")

        # 4. Sales transactions (Record 2 sales and mark items as Sold)
        if not Sale.objects.exists():
            # Sale 1: Priya Patel buys Gold Solitaire Ring
            sold_item_1 = items['GLD-RN-001']
            sale1 = Sale.objects.create(
                customer=customers['Priya Patel'],
                jewellery_item=sold_item_1,
                sale_price=sold_item_1.selling_price,
                payment_method='UPI',
                notes='Paid via Google Pay, transaction ID: UPI/20260920/12345'
            )
            sold_item_1.status = 'Sold'
            sold_item_1.save(update_fields=['status'])
            self.stdout.write(f"  + Created Sale #{sale1.id} for {sold_item_1.item_code} (Status updated to Sold)")

            # Sale 2: Rajesh Sharma buys 24K Gold Coin
            sold_item_2 = items['GLD-CN-004']
            sale2 = Sale.objects.create(
                customer=customers['Rajesh Sharma'],
                jewellery_item=sold_item_2,
                sale_price=sold_item_2.selling_price,
                payment_method='Card',
                notes='HDFC Credit Card POS payment'
            )
            sold_item_2.status = 'Sold'
            sold_item_2.save(update_fields=['status'])
            self.stdout.write(f"  + Created Sale #{sale2.id} for {sold_item_2.item_code} (Status updated to Sold)")

        # 5. Enquiries
        if not Enquiry.objects.exists():
            today = timezone.localdate()
            enquiries_data = [
                {
                    'customer': customers['Ananya Desai'],
                    'category': categories['Necklaces'],
                    'interested_item': 'Antique Choker set for wedding in November',
                    'budget': Decimal('400000.00'),
                    'notes': 'Requested catalog images on WhatsApp. Prefers matte gold finish.',
                    'status': 'Interested',
                    'next_followup_date': today + timedelta(days=2),
                },
                {
                    'customer': customers['Vikram Singh'],
                    'category': categories['Rings'],
                    'interested_item': '1.0 Carat Solitaire Engagement Ring',
                    'budget': Decimal('150000.00'),
                    'notes': 'Needs IGI certified diamond. Looking for round brilliant cut.',
                    'status': 'Contacted',
                    'next_followup_date': today,
                },
                {
                    'customer': customers['Meera Joshi'],
                    'category': categories['Bangles & Bracelets'],
                    'interested_item': 'Daily wear 22K Gold Kadas (Pair ~25g)',
                    'budget': Decimal('190000.00'),
                    'notes': 'Will visit store this weekend with family.',
                    'status': 'New',
                    'next_followup_date': today + timedelta(days=4),
                },
            ]

            for enq_info in enquiries_data:
                enq = Enquiry.objects.create(**enq_info)
                self.stdout.write(f"  + Created Enquiry #{enq.id} for {enq.customer.name} ({enq.interested_item})")

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
