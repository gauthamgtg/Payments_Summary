from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import matplotlib.pyplot as plt
import seaborn as sns
from operator import attrgetter

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
        "Refunded": "Refunded",
        "Partial Refund": "Partial Refund"
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
    pagination = []
    ellipsis = "..."
    if total_pages <= max_visible_pages + 2:
        pagination = list(range(1, total_pages + 1))
    else:
        pagination.append(1)
        if current_page > 3:
            pagination.append(ellipsis)
        start = max(2, current_page - 2)
        end = min(total_pages - 1, current_page + 2)
        pagination.extend(range(start, end + 1))
        if current_page < total_pages - 2:
            pagination.append(ellipsis)
        pagination.append(total_pages)
    return pagination

def generate_category_chart(data, category):
    category_data = data[data["Adspends / Subscription"] == category]
    category_summary = category_data.groupby("Month").agg({
        "Converted Amount": "sum",
        "Status": lambda x: (x == "Paid").sum(),
        "Converted Amount Refunded": "sum"
    }).rename(columns={"Converted Amount": "Total Payment", "Status": "Successful Payments"})
    category_summary["Failed Payments"] = category_data[
        (category_data["Status"] != "Paid") & (category_data["Status"] != "Refunded") & (data["Status"] != "Partial Refund")
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

def generate_pie_chart(data, column, title):
    counts = data[column].value_counts()
    return px.pie(
        names=counts.index,
        values=counts.values,
        title=title
    )

def generate_line_chart(data, x, y, title, labels):
    chart = px.line(
        data,
        x=x,
        y=y,
        title=title,
        markers=True,
        labels=labels
    )
    for i, row in data.iterrows():
        chart.add_annotation(
            x=row[x],
            y=row[y],
            text=f"${row[y]:,.2f}",
            showarrow=False,
            font=dict(size=10, color="black"),
            bgcolor="white",
            bordercolor="black",
            borderwidth=1,
            borderpad=4
        )
    return chart


def perform_cohort_analysis(df):
    # Convert subscription start to a datetime
    df['Created date'] = pd.to_datetime(df['Created date'])

    # Create columns for cohort and subscription month, and convert to period for grouping
    df['sub_month'] = df['Created date'].dt.to_period('M')
    df['cohort'] = df.groupby('Customer Email')['Created date'].transform('min').dt.to_period('M')

    # Group data by cohort and subscription month, and count unique customers
    df_cohort = df.groupby(['cohort', 'sub_month']).agg(n_customers=('Customer Email', 'nunique')).reset_index(drop=False)

    # Calculate the period number (time passed since cohort start)
    df_cohort['period_number'] = (df_cohort.sub_month - df_cohort.cohort).apply(attrgetter('n'))

    # Pivot the table to get the cohort by period matrix
    cohort_pivot = df_cohort.pivot_table(index='cohort', columns='period_number', values='n_customers')

    # Convert cohort period to string for JSON serialization
    cohort_pivot.index = cohort_pivot.index.astype(str)
    cohort_pivot.columns = cohort_pivot.columns.astype(str)

    if cohort_pivot.empty:
        return "No cohort data available.", "No retention data available."

    cohort_size = cohort_pivot.iloc[:, 0]
    retention_table = cohort_pivot.divide(cohort_size, axis=0)

    return cohort_pivot, retention_table

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/overview')
def overview():
   
   # Get unique sources for the filter dropdown
    unique_sources = data['Source'].dropna().unique().tolist()
    unique_sources.sort()  # Sort the sources alphabetically

    # Get the selected source from the request, default to "All"
    selected_source = request.args.get('source', 'All')

    # Filter the data based on the selected source
    if selected_source != 'All':
        filtered_data = data[data['Source'] == selected_source]
    else:
        filtered_data = data

    # Calculate metrics
    total_payment_value = filtered_data["Converted Amount"].sum()
    total_success = filtered_data[filtered_data["Status"] == "Paid"]["Converted Amount"].sum()
    total_failed = filtered_data[(filtered_data["Status"] != "Paid") & (filtered_data["Status"] != "Refunded") & (filtered_data["Status"] != "Partial Refund")]["Converted Amount"].sum()
    total_disputed_amount = filtered_data["Disputed Amount"].sum()
    total_fee = filtered_data["Fee"].sum()
    total_refunded = filtered_data["Converted Amount Refunded"].sum()

    # Generate pie charts
    pie_chart_count = generate_pie_chart(filtered_data, "Status", "Success vs Failed vs Refunded (Count)")
    status_amount = filtered_data.groupby("Status")["Converted Amount"].sum()
    pie_chart_amount = generate_pie_chart(status_amount.reset_index(), "Status", "Success vs Failed vs Refunded (Amount)")

    # Monthly revenue analysis
    filtered_data["Month"] = pd.to_datetime(filtered_data["Created date"], errors='coerce').dt.to_period("M").astype(str)
    monthly_revenue = filtered_data.groupby("Month")["Converted Amount"].sum().reset_index()
    revenue_chart = generate_line_chart(monthly_revenue, "Month", "Converted Amount", "Monthly Revenue", {"Month": "Month", "Converted Amount": "Revenue"})

    # Group by Month and aggregate
    monthly_summary = filtered_data.groupby("Month").agg(
        Total_Payments=("Converted Amount", "sum"),
        Total_Refunded=("Converted Amount Refunded", "sum"),
        Total_Successful=("Converted Amount", lambda x: x[filtered_data.loc[x.index, "Status"] == "Paid"].sum()),
        Total_Failed=("Converted Amount", lambda x: x[(filtered_data.loc[x.index, "Status"] != "Paid") & (filtered_data.loc[x.index, "Status"] != "Refunded") & (filtered_data.loc[x.index, "Status"] != "Partial Refund")].sum())
    ).reset_index()

    graph_data = monthly_summary.drop(columns=["Total_Payments"])
    melted_graph_data = graph_data.melt(id_vars=["Month"], var_name="Type", value_name="Amount")
    stacked_bar_chart = px.bar(melted_graph_data, x="Month", y="Amount", color="Type", barmode="stack")

    melted_graph_data["Percentage"] = melted_graph_data["Amount"] / melted_graph_data.groupby("Month")["Amount"].transform("sum") * 100
    normalized_chart = px.bar(melted_graph_data, x="Month", y="Percentage", color="Type", barmode="relative")

    # Additional category charts
    adspends_chart = generate_category_chart(filtered_data, "Adspends")
    subscription_chart = generate_category_chart(filtered_data, "Subscription")

    # Country summary
    country_summary = filtered_data.groupby("Card Address Country")["Converted Amount"].sum().reset_index().sort_values(by="Converted Amount", ascending=False)
    country_chart = px.bar(country_summary, x="Card Address Country", y="Converted Amount")

    # Failed reasons
    failed_reasons = filtered_data[(filtered_data["Status"] != "Paid") & (filtered_data["Status"] != "Refunded") & (filtered_data["Status"] != "Partial Refund")]["Decline Reason"].value_counts().reset_index()
    failed_reasons.columns = ["Decline Reason", "Count"]
    failed_reason_chart = px.bar(failed_reasons, x="Decline Reason", y="Count")

    cohort_data = {}
    retention_data = {}
    cohort_message = None
    retention_message = None

    cohort_table, retention_table = perform_cohort_analysis(filtered_data)

    # Check if messages are returned instead of tables
    if isinstance(cohort_table, str) and isinstance(retention_table, str):
        cohort_message = cohort_table  # Assign the returned message
        retention_message = retention_table
    else:
        cohort_message = None
        retention_message = None
        cohort_data = cohort_table.fillna(0).astype(int).to_dict(orient='index')
        retention_data = retention_table.fillna(0).round(2).to_dict(orient='index')

    # Convert tables to dictionaries for rendering in the template
   
    return render_template(
        'overview.html',
        total_payment_value=total_payment_value,
        total_success=total_success,
        total_failed=total_failed,
        total_disputed_amount=total_disputed_amount,
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
        cohort_data=cohort_data,
        retention_data=retention_data,
        source_filter=selected_source,
        unique_sources=unique_sources,
        selected_source=selected_source,
        cohort_message=cohort_message,
        retention_message=retention_message,

    )

@app.route('/customer-metrics', methods=['GET', 'POST'])
def customer_metrics():
    ROWS_PER_PAGE = 10
    page = request.args.get('page', 1, type=int)
    email = request.args.get('email', '')

    if request.method == 'POST':
        email = request.form.get('email')

    if email:
        customer_data = data[data['Customer Email'] == email]

        if not customer_data.empty:
            customer_data = customer_data.sort_values(by='Created date', ascending=False)
            metrics = {
                'total_payments': customer_data['Converted Amount'].sum(),
                'total_successful_payments': customer_data[customer_data['Status'] == 'Paid']['Converted Amount'].sum(),
                'total_adspend_transactions': customer_data[(customer_data['Adspends / Subscription'] == 'Adspends') & (customer_data['Status'] == 'Paid')]['Converted Amount'].sum(),
                'total_subscription_transactions': customer_data[(customer_data['Adspends / Subscription'] == 'Subscription') & (customer_data['Status'] == 'Paid')]['Converted Amount'].sum(),
                'total_refunds': customer_data['Converted Amount Refunded'].sum(),
                'total_disputes': customer_data['Disputed Amount'].sum(),
                'total_subscription': customer_data[customer_data['Adspends / Subscription'] == 'Subscription']['Converted Amount'].sum(),
                'total_adspends': customer_data[customer_data['Adspends / Subscription'] == 'Adspends']['Converted Amount'].sum()
            }

            total_rows = customer_data.shape[0]
            start_row = (page - 1) * ROWS_PER_PAGE
            end_row = start_row + ROWS_PER_PAGE
            paginated_data = customer_data.iloc[start_row:end_row]

            customer_data_dict = {
                "columns": list(customer_data.columns),
                "data": paginated_data.values.tolist()
            }

            return render_template(
                'customer_metrics.html',
                metrics=metrics,
                customer_data=customer_data_dict,
                page=page,
                total_pages=(total_rows + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE,
                email=email
            )
        else:
            return render_template('customer_metrics.html', error="No data found for this email.")

    return render_template('customer_metrics.html')

@app.route('/transactions', methods=['GET', 'POST'])
def transactions():
    filtered_data = data.copy()
    records_per_page = int(request.form.get("records_per_page", 10)) if request.method == 'POST' else 10
    page = int(request.args.get("page", 1))

    status_filter = []
    source_filter = []
    captured_filter = "All"
    adspends_filter = "All"
    date_range_start = None
    date_range_end = None
    search_term = None

    status_options = data["Status"].dropna().unique().tolist()
    source_options = data["Source"].dropna().unique().tolist()
    captured_options = [True, False]

    if request.method == 'POST':
        status_filter = request.form.getlist('status')
        source_filter = request.form.getlist('source')
        captured_filter = request.form.get('captured')
        adspends_filter = request.form.get('adspends')
        date_range_start = request.form.get('date_start')
        date_range_end = request.form.get('date_end')
        search_term = request.form.get('search_term')

        if status_filter:
            filtered_data = filtered_data[filtered_data["Status"].isin(status_filter)]
        if source_filter:
            filtered_data = filtered_data[filtered_data["Source"].isin(source_filter)]
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

    total_records = len(filtered_data)
    total_pages = (total_records + records_per_page - 1) // records_per_page
    start = (page - 1) * records_per_page
    end = start + records_per_page
    paginated_data = filtered_data.iloc[start:end]

    pagination = generate_pagination(page, total_pages)

    transactions_data = {
        "columns": list(filtered_data.columns),
        "data": paginated_data.values.tolist(),
    }

    return render_template(
        'transactions.html',
        transactions_data=transactions_data,
        pagination=pagination,
        current_page=page,
        total_pages=total_pages,
        total_records=total_records,
        records_per_page=records_per_page,
        status_options=status_options,
        source_options=source_options,
        captured_options=captured_options,
        selected_status=status_filter,
        selected_source=source_filter,
        selected_captured=captured_filter,
    )

@app.route('/refunds')
def refunds():
    total_refunded_amount = data["Converted Amount Refunded"].sum()
    total_refunds = data[data["Converted Amount Refunded"] > 0].shape[0]
    refund_trends = data[data["Converted Amount Refunded"] > 0].groupby("Created date")["Converted Amount Refunded"].sum().reset_index()
    refund_chart = px.line(refund_trends, x="Created date", y="Converted Amount Refunded", title="Refund Trends Over Time")
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
    dispute_chart = px.bar(dispute_reason_counts, x=dispute_reason_counts.index, y=dispute_reason_counts.values, title="Dispute Reasons", labels={"x": "Reason", "y": "Count"})
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
        "Converted Amount Refunded": "sum",
        "Gateway charges in USD": "sum"
    }).reset_index()
    revenue_trends = data.groupby(["Adspends / Subscription", "Created date"]).agg({"Amount": "sum"}).reset_index()
    charts = {}
    for category in revenue_trends["Adspends / Subscription"].unique():
        category_data = revenue_trends[revenue_trends["Adspends / Subscription"] == category]
        charts[category] = px.line(category_data, x="Created date", y="Amount", title=f"{category} Revenue Trend Over Time").to_html(full_html=False)
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
