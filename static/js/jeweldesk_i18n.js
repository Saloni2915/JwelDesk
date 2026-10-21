/**
 * JewelDesk Multi-Language Engine (English / Hindi)
 * Complete real-time UI localization for JewelDesk Jewelry ERP.
 * Translates sidebar navigation, top navigation, tables, forms, buttons,
 * status badges, KPI cards, and all module pages dynamically into Hindi.
 */

(function () {
    'use strict';

    // Comprehensive English -> Hindi Dictionary curated specifically for JewelDesk ERP
    const HINDI_TRANSLATIONS = {
        // --- 1. Top Navbar, User Profile & Impersonation ---
        "Super Admin": "सुपर एडमिन",
        "Tenant Admin": "स्टोर एडमिन",
        "Store Owner": "दुकान मालिक",
        "Staff": "स्टाफ",
        "Admin": "प्रशासक",
        "Logout": "लॉग आउट",
        "Sign Out": "साइन आउट",
        "Exit Impersonation": "उपयोगकर्ता मोड समाप्त करें",
        "Language": "भाषा",
        "System Language": "सिस्टम की भाषा",
        "Switch Language": "भाषा बदलें",
        "Switch Language / भाषा बदलें": "भाषा बदलें (Switch Language)",
        "Language: English": "भाषा: अंग्रेजी",
        "Language: Hindi": "भाषा: हिंदी",
        "Language: 🇬🇧 English": "भाषा: 🇬🇧 English",
        "Language: 🇮🇳 हिंदी": "भाषा: 🇮🇳 हिंदी",

        // --- 2. Sidebar Navigation & Top-Level Modules ---
        "Dashboard": "डैशबोर्ड",
        "Overview": "विवरण / सारांश",
        "Sales & Exchange": "बिक्री एवं एक्सचेंज",
        "Sales and Exchange": "बिक्री एवं एक्सचेंज",
        "Sales & Billing": "बिक्री एवं बिलिंग",
        "Sales and Billing": "बिक्री एवं बिलिंग",
        "Sales & Invoices": "बिक्री एवं बिल",
        "Sales and Invoices": "बिक्री एवं बिल",
        "Point of Sale": "बिक्री काउंटर (POS)",
        "Retail Counter (POS)": "रिटेल काउंटर (POS)",
        "Point of Sale (POS)": "बिक्री काउंटर (POS)",
        "Retail Sales": "खुदरा बिक्री",
        "Sales History": "बिक्री इतिहास",
        "New Sale": "नई बिक्री",
        "New Sale (POS)": "नई बिक्री (POS)",
        "+ New Sale": "+ नई बिक्री",
        "All Invoices": "सभी बिल / रसीदें",
        "All Invoices & Bills": "सभी बिल एवं रसीदें",
        "All Sales": "सभी बिक्री",
        "All Sales & Bills": "सभी बिक्री एवं बिल",
        "Quick Sale": "त्वरित बिक्री",
        "Old Gold Exchange": "पुराना सोना एक्सचेंज",
        "Old Gold Buyback": "पुराना सोना बायबैक",
        "Old Gold History": "पुराना सोना इतिहास",
        "Old Gold Transactions": "पुराना सोना लेन-देन",
        "Payments & Receipts": "भुगतान एवं रसीदें",
        "Payments & Khata": "भुगतान एवं खाता बही",
        "Sales Inquiries": "बिक्री पूछताछ",
        "Customer Enquiries": "ग्राहक पूछताछ",
        "Retail Sales Report": "खुदरा बिक्री रिपोर्ट",

        // --- 3. Wholesale & B2B Module ---
        "Wholesale & B2B": "थोक व्यापार (B2B)",
        "Wholesale and B2B": "थोक व्यापार (B2B)",
        "Wholesale (B2B)": "थोक व्यापार (B2B)",
        "Wholesale B2B": "थोक व्यापार (B2B)",
        "Wholesale Dashboard": "थोक डैशबोर्ड",
        "Retailers / Parties": "खुदरा विक्रेता / पार्टियां",
        "Retailers and Parties": "खुदरा विक्रेता / पार्टियां",
        "Products & Pricing": "उत्पाद एवं मूल्य निर्धारण",
        "Products and Pricing": "उत्पाद एवं मूल्य निर्धारण" ,
        "Wholesale Orders": "थोक ऑर्डर्स",
        "Dispatches & Shipping": "प्रेषण एवं शिपिंग",
        "Dispatches and Shipping": "प्रेषण एवं शिपिंग",
        "Wholesale Invoices": "थोक बिल / इनवॉइस",
        "Wholesale Customers": "थोक खरीदार (पार्टियां)",
        "Wholesale Reports": "थोक रिपोर्ट्स",
        "Payments Received": "प्राप्त भुगतान",
        "Party Ledger": "पार्टी खाता बही",
        "Returns & Credit Notes": "वापसी एवं क्रेडिट नोट",
        "Returns and Credit Notes": "वापसी एवं क्रेडिट नोट",

        // --- 4. Outstation Sales & Trips ---
        "Outstation Sales": "आउटस्टेशन बिक्री",
        "All Trips & Dashboard": "सभी यात्राएं एवं डैशबोर्ड",
        "New Trip": "नई आउटस्टेशन यात्रा",
        "+ New Trip": "+ नई यात्रा",
        "Exhibitions & Expos": "प्रदर्शनी एवं एक्सपो",
        "Register Exhibition": "नई प्रदर्शनी दर्ज करें",

        // --- 5. Stock & Inventory ---
        "Jewellery Stock": "आभूषण स्टॉक",
        "Inventory": "इन्वेंट्री स्टॉक",
        "All Stock Items": "सभी स्टॉक आभूषण",
        "Stock History": "स्टॉक गतिविधि इतिहास",
        "Stock Movement": "स्टॉक गतिविधि",
        "Stock Movement History": "स्टॉक आवागमन इतिहास",
        "Import Stock": "स्टॉक आयात (Excel/CSV)",
        "Bulk Import Items": "थोक माल आयात",
        "Barcode / Tag Print": "बारकोड / टैग प्रिंट",
        "Categories": "आभूषण श्रेणियां",
        "AI Photo Studio": "एआई फोटो स्टूडियो",

        // --- 6. Pricing & Bullion Rates ---
        "Pricing & Rates": "मूल्य एवं दरें",
        "Pricing and Rates": "मूल्य एवं दरें",
        "Price Calculator": "मूल्य कैलकुलेटर",
        "Daily Metal Rates": "दैनिक धातु भाव",
        "Metal Rates": "धातु के भाव (Metal Rates)",
        "Making Charges": "मेकिंग चार्ज नियम",

        // --- 7. Customers & CRM ---
        "Customers & CRM": "ग्राहक एवं खाता",
        "Customers": "ग्राहक (कस्टमर)",
        "All Customers": "सभी ग्राहक",
        "Add Customer": "नया ग्राहक जोड़ें",
        "+ Add Customer": "+ नया ग्राहक जोड़ें",
        "Khata / Ledger": "खाता बही (उधार/जमा)",
        "Customer Ledger": "ग्राहक खाता बही",
        "Customer Khata": "ग्राहक खाता",

        // --- 8. Custom Orders ---
        "Custom Orders": "कस्टम ऑर्डर्स",
        "All Custom Orders": "सभी कस्टम ऑर्डर्स",
        "New Custom Order": "नया कस्टम ऑर्डर",
        "+ New Custom Order": "+ नया कस्टम ऑर्डर",

        // --- 9. Karigar & Workshop ---
        "Karigar & Workshop": "कारीगर एवं कार्यशाला",
        "Karigar and Workshop": "कारीगर एवं कार्यशाला",
        "Karigar": "कारीगर",
        "Karigar Dashboard": "कारीगर डैशबोर्ड",
        "All Karigars": "सभी कारीगर",
        "Karigar List": "कारीगर सूची",
        "Add Karigar": "नया कारीगर जोड़ें",
        "+ Add Karigar": "+ नया कारीगर जोड़ें",
        "Work Assignments": "काम सौंपें (जॉब कार्ड)",
        "Karigar Jobs": "कारीगर कार्य / जॉब्स",
        "New Work Assignment": "नया कार्य सौंपें",
        "Pending & Overdue": "लंबित एवं बकाया कार्य",
        "Pending and Overdue": "लंबित एवं बकाया कार्य",
        "Work Assignment": "कारीगर कार्य",
        "Karigar Payments": "कारीगर भुगतान",
        "Karigar Reports": "कारीगर रिपोर्ट्स",
        "Settlement History": "भुगतान एवं निपटान इतिहास",

        // --- 10. Team & Administration ---
        "Team & HR": "टीम एवं कर्मचारी",
        "Team and HR": "टीम एवं कर्मचारी",
        "Employees": "कर्मचारी सूची",
        "Employee List": "कर्मचारी सूची",
        "Add Employee": "नया कर्मचारी जोड़ें",
        "+ Add Employee": "+ नया कर्मचारी जोड़ें",
        "Roles & Permissions": "भूमिकाएं एवं अनुमतियां",
        "Roles and Permissions": "भूमिकाएं एवं अनुमतियां",
        "Branches": "दुकान शाखाएं",
        "My Profile": "मेरी प्रोफाइल",

        // --- 11. Reports & Analytics ---
        "Reports & Analytics": "रिपोर्ट्स एवं विश्लेषण",
        "Reports and Analytics": "रिपोर्ट्स एवं विश्लेषण",
        "Reports": "रिपोर्ट्स एवं विश्लेषण",
        "Sales Report": "बिक्री रिपोर्ट",
        "Inventory Report": "स्टॉक रिपोर्ट",
        "GST Report": "जीएसटी रिपोर्ट",
        "Tax Summary": "कर सारांश",

        // --- 12. Settings Module ---
        "Settings": "सेटिंग्स (Settings)",
        "Settings (Settings)": "सेटिंग्स (Settings)",
        "Company Settings": "दुकान सेटिंग्स",
        "Shop Settings": "दुकान सेटिंग्स",
        "Menu Bar Settings": "मेनू बार सेटिंग्स",
        "Sidebar Menu Bar Settings": "साइडबार मेनू सेटिंग्स",
        "Navigation Settings": "नेविगेशन सेटिंग्स",
        "Menu Bar Visibility & Customization": "मेनू बार दृश्यता एवं अनुकूलन",
        "Menu Bar Visibility and Customization": "मेनू बार दृश्यता एवं अनुकूलन",
        "Configure Navigation Menus": "नेविगेशन मेनू कॉन्फ़िगर करें",
        "Changes apply immediately to your active store navigation sidebar": "बदलाव तुरंत आपकी दुकान के साइडबार नेविगेशन पर लागू होते हैं",
        "Menu Module Option": "मेनू मॉड्यूल विकल्प",
        "Hide / Show Control": "छिपाएं / दिखाएं नियंत्रण",
        "Save All Changes": "सभी बदलाव सहेजें",
        "Unhide All Menus": "सभी मेनू वापस लाएं",
        "Total Menu Modules": "कुल मेनू मॉड्यूल",
        "Currently Visible": "वर्तमान में दिखाई देने वाले",
        "Hidden from Sidebar": "साइडबार से छिपे हुए",
        "Permanent Access:": "स्थायी पहुंच:",
        "Settings menu option is locked visible so you can always re-configure navigation.": "सेटिंग्स मेनू विकल्प हमेशा सुरक्षित और दिखाई देगा ताकि आप कभी भी नेविगेशन पुनः कॉन्फ़िगर कर सकें।",
        "How It Works": "यह कैसे काम करता है?",
        "Themes": "थीम्स / रंग",
        "Themes / Colors": "थीम्स / रंग",
        "Get the App": "मोबाइल ऐप डाउनलोड",
        "APK / Install": "ऐप इंस्टॉल",

        // --- 13. Common Action Buttons & Form Controls ---
        "Save": "सहेजें",
        "Save Settings": "सेटिंग्स सहेजें",
        "Save Changes": "बदलाव सहेजें",
        "Save Logo Now": "लोगो अभी सहेजें",
        "Save & Apply New Logo": "नया लोगो सहेजें एवं लागू करें",
        "Restore JewelDesk Logo": "डिफ़ॉल्ट लोगो पुनर्स्थापित करें",
        "Cancel": "रद्द करें",
        "Delete": "हटाएं",
        "Edit": "संपादित करें",
        "Update": "अपडेट करें",
        "View": "देखें",
        "Details": "विवरण",
        "Print": "प्रिंट करें",
        "Print Invoice": "बिल प्रिंट करें",
        "Download": "डाउनलोड",
        "Download PDF": "पीडीएफ डाउनलोड करें",
        "Download Invoice": "बिल डाउनलोड करें",
        "Export": "निर्यात (Export)",
        "Export CSV": "सीएसवी निर्यात",
        "Export Excel": "एक्सेल निर्यात",
        "Import": "आयात (Import)",
        "Search": "खोजें",
        "Filter": "फ़िल्टर",
        "Clear": "साफ़ करें",
        "Reset": "रीसेट करें",
        "Back": "वापस जाएं",
        "Close": "बंद करें",
        "Submit": "जमा करें",
        "Confirm": "पुष्टि करें",
        "Apply": "लागू करें",
        "Add": "जोड़ें",
        "Add Item": "आभूषण जोड़ें",
        "Add New Item": "नया आभूषण जोड़ें",
        "Add Row": "नई पंक्ति जोड़ें",
        "Remove": "हटाएं",
        "Proceed": "आगे बढ़ें",
        "Pay Now": "अभी भुगतान करें",
        "Record Payment": "भुगतान दर्ज करें",

        // --- 14. Status Badges ---
        "Active": "सक्रिय",
        "Inactive": "निष्क्रिय",
        "Paid": "भुगतान पूर्ण",
        "Unpaid": "अदत्त (बाकी)",
        "Partial": "आंशिक भुगतान",
        "Partially Paid": "आंशिक भुगतान",
        "Pending": "लंबित",
        "In Progress": "प्रगति पर",
        "Completed": "पूर्ण",
        "Delivered": "डिलीवर हो गया",
        "Cancelled": "रद्द",
        "In Stock": "स्टॉक में उपलब्ध",
        "Out of Stock": "स्टॉक समाप्त",
        "Low Stock": "कम स्टॉक",
        "Visible": "दिखाई देगा",
        "Hidden": "छिपा हुआ",
        "Hide ON": "छिपाएं (ON)",
        "Hide OFF": "दिखाएं (OFF)",

        // --- 15. Table Headers, Financial & Bill Terms ---
        "S.No": "क्र.सं.",
        "S.No.": "क्र.सं.",
        "Sr. No.": "क्र.सं.",
        "Item": "आभूषण / वस्तु",
        "Item Name": "आभूषण का नाम",
        "Item Description": "आभूषण विवरण",
        "Product": "उत्पाद",
        "SKU": "एसकेयू कोड",
        "Item Code": "आभूषण कोड",
        "Barcode": "बारकोड",
        "HUID": "एचयूआईडी (HUID)",
        "Category": "श्रेणी",
        "Metal": "धातु",
        "Metal Type": "धातु का प्रकार",
        "Gold": "सोना",
        "Silver": "चांदी",
        "Diamond": "हीरा",
        "Platinum": "प्लैटिनम",
        "Gross Weight": "सकल वज़न (Gross Wt)",
        "Gross Wt": "सकल वज़न",
        "Gross Wt.": "सकल वज़न",
        "Net Weight": "शुद्ध वज़न (Net Wt)",
        "Net Wt": "शुद्ध वज़न",
        "Net Wt.": "शुद्ध वज़न",
        "Pure Weight": "शुद्ध वज़न",
        "Stone Weight": "नगीना वज़न",
        "Stone Wt": "नगीना वज़न",
        "Purity": "शुद्धता",
        "Karat": "कैरेट",
        "Rate": "दर / भाव",
        "Metal Rate": "धातु भाव",
        "Gold Rate": "सोने का भाव",
        "Silver Rate": "चांदी का भाव",
        "Making Charge": "मेकिंग चार्ज",
        "Making Charges": "मेकिंग चार्ज (बनाई)",
        "Wastage": "घटाव / वेस्टेज",
        "Quantity": "मात्रा (संख्या)",
        "Qty": "मात्रा",
        "Pieces": "नग / पीस",
        "Total Amount": "कुल राशि",
        "Subtotal": "उप-योग (Subtotal)",
        "Discount": "छूट (Discount)",
        "Tax": "कर (Tax)",
        "GST": "जीएसटी (GST)",
        "GSTIN": "जीएसटी नंबर (GSTIN)",
        "GSTIN Number": "जीएसटी नंबर",
        "CGST": "सीजीएसटी",
        "SGST": "एसजीएसटी",
        "IGST": "आईजीएसटी",
        "Grand Total": "कुल देय राशि (Grand Total)",
        "Final Amount": "अंतिम राशि",
        "Paid Amount": "प्राप्त राशि",
        "Balance": "बकाया राशि",
        "Balance Amount": "बकाया राशि",
        "Due Amount": "देय राशि",
        "Payment Mode": "भुगतान माध्यम",
        "Payment Method": "भुगतान माध्यम",
        "All Payment Methods": "सभी भुगतान माध्यम",
        "Cash": "नकद (Cash)",
        "UPI": "यूपीआई (UPI)",
        "Card": "डेबिट/क्रेडिट कार्ड",
        "Bank Transfer": "बैंक ट्रांसफर (NEFT/RTGS)",
        "Cheque": "चेक (Cheque)",
        "Invoice": "बिल / रसीद",
        "Invoice #": "बिल संख्या",
        "Invoice Number": "बिल संख्या",
        "Invoice No": "बिल संख्या",
        "Invoice No.": "बिल संख्या",
        "Invoice Date": "बिल दिनांक",
        "Date": "दिनांक / तारीख",
        "Date & Time": "दिनांक एवं समय",
        "Customer": "ग्राहक",
        "Customer Name": "ग्राहक का नाम",
        "Customer Details": "ग्राहक विवरण",
        "1. Customer Details": "1. ग्राहक विवरण",
        "Customer Name & Contact": "ग्राहक का नाम एवं संपर्क",
        "Phone": "फ़ोन / मोबाइल",
        "Mobile": "मोबाइल नंबर",
        "Phone Number": "फ़ोन नंबर",
        "Contact Phone / Mobile": "संपर्क फ़ोन / मोबाइल",
        "Email": "ईमेल",
        "Business Email": "व्यावसायिक ईमेल",
        "Address": "पता",
        "Shop Address": "दुकान का पता",
        "City": "शहर",
        "State": "राज्य",
        "Pincode": "पिन कोड",
        "Notes": "टिप्पणी / नोट",
        "Action": "कार्रवाई",
        "Actions": "कार्रवाई",
        "Status": "स्थिति",
        "Created At": "सृजन दिनांक",
        "Updated At": "अंतिम अपडेट",
        "Today's Sales": "आज की बिक्री",
        "Lifetime Revenue": "कुल आय (Lifetime)",
        "Total Invoices": "कुल बिल / इनवॉइस",
        "Counter Status": "काउंटर स्थिति",
        "Active & Ready": "सक्रिय एवं तैयार",
        "Counter #01": "काउंटर #01",
        "List of all sales bills, invoices, and customer payments": "सभी बिक्री बिलों, रसीदों और ग्राहक भुगतानों की सूची",
        "Exchange customer old jewellery for new jewellery items": "ग्राहक के पुराने आभूषण को नए आभूषण के बदले एक्सचेंज करें",
        "Transactions History": "लेन-देन इतिहास",
        "Outright Buyback": "सीधा बायबैक (नकद)",

        // --- 16. Common Jewelry Ornaments ---
        "Ring": "अंगूठी (Ring)",
        "Rings": "अंगूठियां",
        "Gold Ring": "सोने की अंगूठी",
        "Diamond Ring": "हीरे की अंगूठी",
        "Necklace": "हार / नेकलेस",
        "Chain": "चेन (Chain)",
        "Bangles": "कंगन / चूड़ियां",
        "Bracelet": "ब्रेसलेट",
        "Earrings": "झुमके / बालियां",
        "Pendant": "पेंडेंट",
        "Mangalsutra": "मंगलसूत्र",
        "Payal": "पायल",
        "Nosepin": "नथ / नोज़पिन",
        "Coin": "सिक्का (Coin)",
        "Gold Coin": "सोने का सिक्का",
        "Silver Coin": "चांदी का सिक्का",
        "Bar": "बार / सिल्ली",
        "Gold Bar": "सोने का बार / सिल्ली",
        "Silver Bar": "चांदी का बार / सिल्ली",

        // --- 17. Menu Options Descriptions ---
        "Showroom dashboard overview, KPI summary statistics, and daily business metrics.": "शोरूम डैशबोर्ड विवरण, मुख्य केपीआई आंकड़े और दैनिक व्यापार मेट्रिक्स।",
        "Counter retail sales billing, payments ledger, old gold exchange and buyback records.": "काउंटर खुदरा बिक्री बिलिंग, भुगतान लेज़र, पुराना सोना एक्सचेंज और बायबैक रिकॉर्ड्स।",
        "B2B merchant portal, retailer parties, wholesale bulk order booking, dispatches, and ledger.": "B2B व्यापारी पोर्टल, खुदरा विक्रेता पार्टियां, थोक ऑर्डर बुकिंग, प्रेषण और लेज़र।",
        "Outstation sales trips, travelling representative orders, and exhibition expos.": "आउटस्टेशन बिक्री यात्राएं, प्रतिनिधि ऑर्डर्स और आभूषण प्रदर्शनी एक्सपो।",
        "Physical stock items, weights, purity grades, BIS hallmarks, HUIDs & AI Photo Studio.": "भौतिक स्टॉक आभूषण, वज़न, शुद्धता ग्रेड, बीआईएस हॉलमार्क, एचयूआईडी और एआई फोटो स्टूडियो।",
        "Live gold & silver bullion market rates, making charges, and retail price calculator.": "सोना एवं चांदी के लाइव बाजार भाव, मेकिंग चार्ज नियम और खुदरा मूल्य कैलकुलेटर।",
        "Customer profiles, loyalty directory, outstanding credit khata, and sales enquiries.": "ग्राहक प्रोफ़ाइल, लॉयल्टी डायरेक्टरी, बकाया उधारी खाता और बिक्री पूछताछ।",
        "Bespoke ornament customer orders, custom designs, CAD milestones, and delivery tracking.": "कस्टम आभूषण ऑर्डर्स, विशेष डिज़ाइन, सीएडी चरण और डिलीवरी ट्रैकिंग।",
        "Artisan job cards, gold issue/receive weights, scrap recovery, and karigar wage settlements.": "कारीगर जॉब कार्ड, सोना जारी/प्राप्ति वज़न, छीलन रिकवरी और मजदूरी भुगतान।",
        "Counter sales staff, store employees, role-based module permissions, and showroom branches.": "काउंटर सेल्स स्टाफ, दुकान कर्मचारी, भूमिका-आधारित अनुमतियां और शाखाएं।",
        "Comprehensive retail GST invoices, wholesale turnover ledgers, and artisan workshop reports.": "विस्तृत खुदरा जीएसटी बिल, थोक टर्नओवर लेज़र और कारीगर वर्कशॉप रिपोर्ट्स।",
        "JewelDesk Progressive Web App (PWA) and Android APK install shortcut in sidebar.": "JewelDesk प्रोग्रेसिव वेब ऐप (PWA) और एंड्रॉइड एपीके इंस्टॉल शॉर्टकट।",

        // --- 18. Messages, Confirmation Dialogs & Placeholders ---
        "Search by customer name, mobile, tag #, HUID, or item name...": "ग्राहक का नाम, मोबाइल, टैग #, HUID या आभूषण से खोजें...",
        "Are you sure?": "क्या आप सुनिश्चित हैं?",
        "Are you sure you want to unhide all menu options?": "क्या आप सभी मेनू विकल्प वापस लाना चाहते हैं?",
        "Confirm Delete": "हटाने की पुष्टि करें",
        "No records found": "कोई रिकॉर्ड उपलब्ध नहीं है",
        "No data available": "कोई डेटा उपलब्ध नहीं है",
        "Loading...": "लोड हो रहा है...",
        "Success": "सफलता",
        "Error": "त्रुटि",
        "Warning": "चेतावनी",
        "Information": "सूचना",
        "All rights reserved.": "सर्वाधिकार सुरक्षित।"
    };

    // Fast exact match map
    const DICTIONARY_MAP = new Map(Object.entries(HINDI_TRANSLATIONS));

    // Lowercase normalized map for case-insensitive and uppercase matching
    const LOWER_MAP = new Map();
    for (const [key, value] of DICTIONARY_MAP.entries()) {
        const lowerKey = key.trim().toLowerCase();
        if (!LOWER_MAP.has(lowerKey)) {
            LOWER_MAP.set(lowerKey, value);
        }
    }

    // Tags that should NEVER be translated
    const IGNORE_TAGS = new Set([
        'SCRIPT', 'STYLE', 'CODE', 'PRE', 'NOSCRIPT', 'SVG', 'PATH', 'IFRAME'
    ]);

    // Unescape common HTML entities
    function unescapeEntities(str) {
        if (!str || str.indexOf('&') === -1) return str;
        return str
            .replace(/&amp;/g, '&')
            .replace(/&quot;/g, '"')
            .replace(/&#39;/g, "'")
            .replace(/&lt;/g, '<')
            .replace(/&gt;/g, '>');
    }

    function getNormalizedText(str) {
        if (!str) return '';
        return unescapeEntities(str).replace(/\s+/g, ' ').trim();
    }

    function translateText(text) {
        const cleaned = getNormalizedText(text);
        if (!cleaned) return null;

        // 1. Exact match
        if (DICTIONARY_MAP.has(cleaned)) {
            return DICTIONARY_MAP.get(cleaned);
        }

        // 2. Case-insensitive / uppercase match
        const lower = cleaned.toLowerCase();
        if (LOWER_MAP.has(lower)) {
            return LOWER_MAP.get(lower);
        }

        // 3. Match with leading symbol (+, -, *, •, ₹)
        const symbolMatch = cleaned.match(/^([+\-*•₹]\s*)(.+)$/);
        if (symbolMatch) {
            const sym = symbolMatch[1];
            const core = symbolMatch[2];
            const coreTrans = translateText(core);
            if (coreTrans) {
                return sym + coreTrans;
            }
        }

        return null;
    }

    function translateNode(node) {
        if (!node) return;

        // 1. Text node
        if (node.nodeType === Node.TEXT_NODE) {
            const original = node.nodeValue;
            if (!original || !original.trim()) return;

            const translated = translateText(original);
            if (translated) {
                // Preserve leading and trailing whitespace
                const leading = (original.match(/^\s*/) || [''])[0];
                const trailing = (original.match(/\s*$/) || [''])[0];
                node.nodeValue = leading + translated + trailing;
            }
            return;
        }

        // 2. Element node
        if (node.nodeType === Node.ELEMENT_NODE) {
            if (IGNORE_TAGS.has(node.tagName)) return;

            // Handle placeholders
            if (node.hasAttribute('placeholder')) {
                const ph = node.getAttribute('placeholder');
                const tPh = translateText(ph);
                if (tPh) node.setAttribute('placeholder', tPh);
            }

            // Handle title tooltips
            if (node.hasAttribute('title')) {
                const tit = node.getAttribute('title');
                const tTit = translateText(tit);
                if (tTit) node.setAttribute('title', tTit);
            }

            // Handle aria-label
            if (node.hasAttribute('aria-label')) {
                const al = node.getAttribute('aria-label');
                const tAl = translateText(al);
                if (tAl) node.setAttribute('aria-label', tAl);
            }

            // Handle input submit/button value
            if (node.tagName === 'INPUT' && (node.type === 'submit' || node.type === 'button' || node.type === 'reset')) {
                const val = node.value;
                const tVal = translateText(val);
                if (tVal) node.value = tVal;
            }

            // Recurse child nodes
            let child = node.firstChild;
            while (child) {
                translateNode(child);
                child = child.nextSibling;
            }
        }
    }

    let isTranslating = false;

    function applyHindiTranslations(root) {
        if (isTranslating) return;
        isTranslating = true;
        try {
            translateNode(root || document.body);
        } finally {
            isTranslating = false;
        }
    }

    // Public API on window
    window.JewelDeskI18n = {
        applyHindi: function (root) {
            applyHindiTranslations(root);
        },
        translateText: translateText,
        dictionary: HINDI_TRANSLATIONS,
        setLanguage: function (langCode) {
            const csrfToken = (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
            fetch('/accounts/settings/language/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ language: langCode })
            })
            .then(function(res) { return res.json(); })
            .then(function() {
                window.location.reload();
            })
            .catch(function() {
                window.location.href = '/accounts/settings/language/?language=' + encodeURIComponent(langCode) + '&next=' + encodeURIComponent(window.location.pathname);
            });
        }
    };

    // Auto-initialize when page is set to Hindi
    function init() {
        const htmlLang = document.documentElement.getAttribute('lang') || '';
        const bodyLang = document.body ? document.body.getAttribute('data-lang') : '';
        const cookieLang = (document.cookie.indexOf('django_language=hi') !== -1 || document.cookie.indexOf('jd_language=hi') !== -1);
        const isHindi = (htmlLang === 'hi' || bodyLang === 'hi' || cookieLang);

        if (isHindi) {
            document.documentElement.setAttribute('lang', 'hi');
            if (document.body) {
                document.body.classList.add('jd-lang-hi');
            }

            // Apply translation to existing DOM immediately
            applyHindiTranslations(document.body);

            // Observe dynamic additions (e.g. modals, AJAX tables, dropdowns)
            let debounceTimer = null;
            const observer = new MutationObserver(function (mutations) {
                if (isTranslating) return;
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(function () {
                    for (let m = 0; m < mutations.length; m++) {
                        const mut = mutations[m];
                        for (let n = 0; n < mut.addedNodes.length; n++) {
                            translateNode(mut.addedNodes[n]);
                        }
                    }
                }, 20);
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
