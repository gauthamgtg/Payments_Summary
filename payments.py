from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io

app = Flask(__name__)

# Load and process data
def load_and_process_data():
    url = "https://docs.google.com/spreadsheets/d/1FKPhjul2X1qDdfcv3EneYOT08FN7lBsUaIGTS_j238g/export?format=csv"
    df = pd.read_csv(url, on_bad_lines="skip")

    df["Description"] = df["Description"].astype(str)
    df["Adspends / Subscription"] = df["Description"].apply(
        lambda x: "Subscription" if "subscription" in x.lower() else "Adspends"
    )

    df['Gateway charges in USD'] = df['Fee']
    df = df.rename(columns={"Created date (UTC)": "Created date"})

    status_mapping = {
        "requires_payment_method": "Failed",
        "Failed": "Failed",
        "Pending": "Failed",
        "canceled": "Failed",
        "requires_confirmation": "Failed",
        "requires_action": "Failed",
        "Paid": "Paid",
        "Refunded": "Refunded"
    }
    df["Status"] = df["Status"].map(status_mapping)

    numeric_columns = [
        "Amount", "Amount Refunded", "Gateway charges in USD",
        "Overages in USD", "Converted Amount", "Converted Amount Refunded",
        "Fee", "Taxes On Fee", "Disputed Amount"
    ]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    date_columns = [
        "Created date", "Refunded date (UTC)", "Dispute Date (UTC)",
        "Dispute Evidence Due (UTC)"
    ]
    for col in date_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%d/%m/%Y")

    return df

data = load_and_process_data()

def generate_pagination(current_page, total_pages, max_visible_pages=5):
    """
    Generate a list of page numbers to display in the pagination.
    Includes ellipses for pages not displayed.
    """
    pagination = []
    ellipsis = "..."
    if total_pages <= max_visible_pages + 2:  # Show all pages if they fit
        pagination = list(range(1, total_pages + 1))
    else:
        # Always show the first and last pages
        pagination.append(1)
        if current_page > 3:
            pagination.append(ellipsis)  # Ellipses before current range

        # Pages around the current page
        start = max(2, current_page - 2)
        end = min(total_pages - 1, current_page + 2)
        pagination.extend(range(start, end + 1))

        if current_page < total_pages - 2:
            pagination.append(ellipsis)  # Ellipses after current range

        pagination.append(total_pages)  # Last page

    return pagination


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/overview')
def overview():
    # Calculate overall metrics
    total_payment_value = data["Converted Amount"].sum()
    total_success = data[data["Status"] == "Paid"]["Converted Amount"].sum()
    total_failed = data[(data["Status"] != "Paid") & (data["Status"] != "Refunded")]["Converted Amount"].sum()
    total_gateway_charge = data["Gateway charges in USD"].sum()
    total_fee = data["Fee"].sum()
    total_refunded = data[data["Status"] == "Refunded"]["Converted Amount Refunded"].sum()

    # Success vs Failed vs Refunded Pie Charts
    status_counts = data["Status"].value_counts()
    pie_chart_count = px.pie(
        names=status_counts.index,
        values=status_counts.values,
        # title="Success vs Failed vs Refunded (Count)",
    )
    status_amount = data.groupby("Status")["Converted Amount"].sum()
    pie_chart_amount = px.pie(
        names=status_amount.index,
        values=status_amount.values,
        # title="Success vs Failed vs Refunded (Amount)",
    )

    # Monthly Revenue Chart
    data["Month"] = pd.to_datetime(data["Created date"], errors='coerce').dt.to_period("M").astype(str)
    monthly_revenue = data.groupby("Month")["Converted Amount"].sum().reset_index()

    # Create a line chart
    revenue_chart = px.line(
        monthly_revenue,
        x="Month",
        y="Converted Amount",
        # title="Monthly Revenue",
        markers=True,
        labels={"Month": "Month", "Converted Amount": "Revenue"}
    )

    # Add annotations for each data point
    for i, row in monthly_revenue.iterrows():
        revenue_chart.add_annotation(
            x=row["Month"],
            y=row["Converted Amount"],
            text=f"${row['Converted Amount']:,.2f}",  # Format value as currency
            showarrow=False,
            font=dict(size=10, color="black"),
            bgcolor="white",
            bordercolor="black",
            borderwidth=1,
            borderpad=4
        )

    # Monthly Payment Breakdown (Refunded, Successful, Failed)
    monthly_summary = data.groupby("Month").agg(
        Total_Payments=("Converted Amount", "sum"),
        Total_Refunded=("Converted Amount Refunded", lambda x: x[data.loc[x.index, "Status"] == "Refunded"].sum()),
        Total_Successful=("Converted Amount", lambda x: x[data.loc[x.index, "Status"] == "Paid"].sum()),
        Total_Failed=("Converted Amount", lambda x: x[data.loc[x.index, "Status"].isin(["Failed", "Other_Failed_Status"])].sum())
    ).reset_index()
    graph_data = monthly_summary.drop(columns=["Total_Payments"])
    melted_graph_data = graph_data.melt(
        id_vars=["Month"], var_name="Type", value_name="Amount"
    )
    stacked_bar_chart = px.bar(
        melted_graph_data,
        x="Month",
        y="Amount",
        color="Type",
        # title="Monthly Payment Breakdown (Refunded, Successful, Failed)",
        barmode="stack"
    )

    # 100% Stacked Bar Chart
    melted_graph_data["Percentage"] = (
        melted_graph_data["Amount"]
        / melted_graph_data.groupby("Month")["Amount"].transform("sum")
        * 100
    )
    normalized_chart = px.bar(
        melted_graph_data,
        x="Month",
        y="Percentage",
        color="Type",
        # title="Monthly Payment Breakdown (100% Stacked)",
        barmode="relative"
    )

    # Adspends and Subscriptions Monthly Breakdown
    adspends_chart = generate_category_chart(data, "Adspends")
    subscription_chart = generate_category_chart(data, "Subscription")

    # Payments by Card Address Country
    country_summary = data.groupby("Card Address Country")["Converted Amount"].sum().reset_index()
    country_summary = country_summary.sort_values(by="Converted Amount", ascending=False)
    country_chart = px.bar(
        country_summary,
        x="Card Address Country",
        y="Converted Amount",
        # title="Payments by Country",
    )

    # Failed Payments Reason Analysis
    failed_reasons = data[(data["Status"] != "Paid") & (data["Status"] != "Refunded")]["Decline Reason"].value_counts().reset_index()
    failed_reasons.columns = ["Decline Reason", "Count"]
    failed_reason_chart = px.bar(
        failed_reasons,
        x="Decline Reason",
        y="Count",
        # title="Overall Failed Payments Reason Analysis"
    )

    return render_template(
        'overview.html',
        total_payment_value=total_payment_value,
        total_success=total_success,
        total_failed=total_failed,
        total_gateway_charge=total_gateway_charge,
        total_fee=total_fee,
        total_refunded=total_refunded,
        pie_chart_count=pie_chart_count.to_html(full_html=False),
        pie_chart_amount=pie_chart_amount.to_html(full_html=False),
        revenue_chart=revenue_chart.to_html(full_html=False),
        stacked_bar_chart=stacked_bar_chart.to_html(full_html=False),
        normalized_chart=normalized_chart.to_html(full_html=False),
        adspends_chart=adspends_chart.to_html(full_html=False),
        subscription_chart=subscription_chart.to_html(full_html=False),
        country_chart=country_chart.to_html(full_html=False),
        failed_reason_chart=failed_reason_chart.to_html(full_html=False),
    )


# Helper function for Adspends and Subscriptions
def generate_category_chart(data, category):
    category_data = data[data["Adspends / Subscription"] == category]
    category_summary = category_data.groupby("Month").agg({
        "Converted Amount": "sum",
        "Status": lambda x: (x == "Paid").sum(),
        "Converted Amount Refunded": "sum"
    }).rename(columns={"Converted Amount": "Total Payment", "Status": "Successful Payments"})
    category_summary["Failed Payments"] = category_data[
        (category_data["Status"] != "Paid") & (category_data["Status"] != "Refunded")
    ].groupby("Month")["Converted Amount"].sum()
    category_summary = category_summary.reset_index()
    return px.bar(
        category_summary.melt(id_vars=["Month"], var_name="Type", value_name="Amount"),
        x="Month",
        y="Amount",
        color="Type",
        title=f"{category} Monthly Payment Breakdown",
        barmode="group"
    )

@app.route('/customer-metrics', methods=['GET', 'POST'])
def customer_metrics():
    # Constants for pagination
    ROWS_PER_PAGE = 10

    # Get the current page number and email from the query parameters
    page = request.args.get('page', 1, type=int)
    email = request.args.get('email', '')

    # If the form is submitted via POST, update the email
    if request.method == 'POST':
        email = request.form.get('email')

    # If an email is provided, filter the data
    if email:
        customer_data = data[data['Customer Email'] == email]

        if not customer_data.empty:
            # Sort data by Created Date in descending order
            customer_data = customer_data.sort_values(by='Created date', ascending=False)

            # Calculate metrics
            metrics = {
                'total_payments': customer_data['Converted Amount'].sum(),
                'total_successful_payments': customer_data[customer_data['Status'] == 'Paid']['Converted Amount'].sum(),
                'total_adspend_transactions': customer_data[(customer_data['Adspends / Subscription'] == 'Adspends') & (customer_data['Status'] == 'Paid')]['Converted Amount'].sum(),
                'total_subscription_transactions': customer_data[(customer_data['Adspends / Subscription'] == 'Subscription') & (customer_data['Status'] == 'Paid')]['Converted Amount'].sum(),
                'total_refunds': customer_data['Amount Refunded'].sum(),
                'total_disputes': customer_data['Disputed Amount'].sum(),
                'total_subscription': customer_data[customer_data['Adspends / Subscription'] == 'Subscription']['Converted Amount'].sum(),
                'total_adspends': customer_data[customer_data['Adspends / Subscription'] == 'Adspends']['Converted Amount'].sum()
            }

            # Pagination logic
            total_rows = customer_data.shape[0]
            start_row = (page - 1) * ROWS_PER_PAGE
            end_row = start_row + ROWS_PER_PAGE
            paginated_data = customer_data.iloc[start_row:end_row]

            # Prepare paginated data for the template
            customer_data_dict = {
                "columns": list(customer_data.columns),  # Column headers
                "data": paginated_data.values.tolist()   # Data rows for the current page
            }

            return render_template(
                'customer_metrics.html',
                metrics=metrics,
                customer_data=customer_data_dict,
                page=page,
                total_pages=(total_rows + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE,  # Calculate total pages
                email=email
            )
        else:
            # No data found for the email
            return render_template('customer_metrics.html', error="No data found for this email.")

    # Render the page initially without any results
    return render_template('customer_metrics.html')

@app.route('/transactions', methods=['GET', 'POST'])
def transactions():
    filtered_data = data.copy()
    records_per_page = int(request.form.get("records_per_page", 10)) if request.method == 'POST' else 10
    page = int(request.args.get("page", 1))

    if request.method == 'POST':
        status_filter = request.form.getlist('status')
        captured_filter = request.form.get('captured')
        adspends_filter = request.form.get('adspends')
        date_range_start = request.form.get('date_start')
        date_range_end = request.form.get('date_end')
        search_term = request.form.get('search_term')

        # Apply filters
        if status_filter:
            filtered_data = filtered_data[filtered_data["Status"].isin(status_filter)]
        if captured_filter == "Yes":
            filtered_data = filtered_data[filtered_data["Captured"] == True]
        elif captured_filter == "No":
            filtered_data = filtered_data[filtered_data["Captured"] == False]
        if adspends_filter and adspends_filter != "All":
            filtered_data = filtered_data[filtered_data["Adspends / Subscription"] == adspends_filter]
        if date_range_start and date_range_end:
            filtered_data = filtered_data[
                (filtered_data["Created date"] >= pd.Timestamp(date_range_start)) &
                (filtered_data["Created date"] <= pd.Timestamp(date_range_end))
            ]
        if search_term:
            filtered_data = filtered_data[
                filtered_data["PaymentIntent ID"].str.contains(search_term, na=False) |
                filtered_data["Customer ID"].str.contains(search_term, na=False)
            ]

    # Pagination logic
    total_records = len(filtered_data)
    total_pages = (total_records + records_per_page - 1) // records_per_page  # Round up division
    start = (page - 1) * records_per_page
    end = start + records_per_page
    paginated_data = filtered_data.iloc[start:end]

    # Generate pagination structure
    pagination = generate_pagination(page, total_pages)

    return render_template(
        'transactions.html',
        transactions_data=paginated_data.to_html(index=False, classes="table table-striped table-hover"),
        pagination=pagination,
        current_page=page,
        total_pages=total_pages,
        total_records=total_records,
        records_per_page=records_per_page,
    )


@app.route('/refunds')
def refunds():
    total_refunded_amount = data["Amount Refunded"].sum()
    total_refunds = data[data["Amount Refunded"] > 0].shape[0]
    refund_trends = data[data["Amount Refunded"] > 0].groupby("Created date")["Amount Refunded"].sum().reset_index()
    refund_chart = px.line(
        refund_trends,
        x="Created date",
        y="Amount Refunded",
        title="Refund Trends Over Time"
    )
    return render_template(
        'refunds.html',
        total_refunded_amount=total_refunded_amount,
        total_refunds=total_refunds,
        refund_chart=refund_chart.to_html(full_html=False)
    )

@app.route('/disputes')
def disputes():
    total_disputed_amount = data["Disputed Amount"].sum()
    total_disputes = data["Dispute Date (UTC)"].count()
    total_disputed_amount_lost = data[(data["Disputed Amount"] > 0) & (data["Dispute Status"] == "lost")].sum()
    total_disputed_amount_won = data[(data["Disputed Amount"] > 0) & (data["Dispute Status"] == "won")].sum()
    dispute_reason_counts = data["Dispute Reason"].value_counts()
    dispute_chart = px.bar(
        dispute_reason_counts,
        x=dispute_reason_counts.index,
        y=dispute_reason_counts.values,
        title="Dispute Reasons",
        labels={"x": "Reason", "y": "Count"}
    )
    return render_template(
        'disputes.html',
        total_disputed_amount=total_disputed_amount,
        total_disputes=total_disputes,
        total_disputed_amount_lost=total_disputed_amount_lost,
        total_disputed_amount_won=total_disputed_amount_won,
        dispute_chart=dispute_chart.to_html(full_html=False)
    )

@app.route('/adspends-vs-subscriptions')
def adspends_vs_subscriptions():
    category_summary = data.groupby("Adspends / Subscription").agg({
        "Amount": "sum",
        "Amount Refunded": "sum",
        "Gateway charges in USD": "sum"
    }).reset_index()
    revenue_trends = data.groupby(["Adspends / Subscription", "Created date"]).agg({"Amount": "sum"}).reset_index()
    charts = {}
    for category in revenue_trends["Adspends / Subscription"].unique():
        category_data = revenue_trends[revenue_trends["Adspends / Subscription"] == category]
        charts[category] = px.line(
            category_data,
            x="Created date",
            y="Amount",
            title=f"{category} Revenue Trend Over Time"
        ).to_html(full_html=False)
    return render_template(
        'adspends_vs_subscriptions.html',
        category_summary=category_summary.to_html(index=False),
        charts=charts
    )

@app.route('/export', methods=['POST'])
def export_csv():
    filtered_data = data.copy()
    csv_buffer = io.StringIO()
    filtered_data.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    return send_file(io.BytesIO(csv_buffer.getvalue().encode()), mimetype="text/csv", as_attachment=True, attachment_filename="filtered_data.csv")

if __name__ == '__main__':
    app.run(debug=True)
