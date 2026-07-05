-- =========================================================
-- SMARTBUS SYSTEM - FULL RERUNNABLE SUPABASE SCHEMA (v3.2)
-- =========================================================

create extension if not exists pgcrypto;

-- =========================================================
-- ENUM TYPES (SAFE RE-RUN)
-- =========================================================

do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role') then
    create type user_role as enum ('admin','driver','customer');
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'trip_status') then
    create type trip_status as enum ('scheduled','started','delayed','completed','cancelled','breakdown');
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'booking_status') then
    create type booking_status as enum ('pending','confirmed','cancelled');
  end if;
end $$;

-- =========================================================
-- TABLES
-- =========================================================

create table if not exists users(
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  email text unique not null,
  phone text,
  password_hash text not null,
  role user_role default 'customer',
  active boolean default true,
  created_at timestamptz default now()
);

create table if not exists drivers(
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique references users(id) on delete cascade,
  license_no text unique not null,
  license_expiry date not null,
  photo_url text,
  created_at timestamptz default now()
);

create table if not exists bus_models(
  id uuid primary key default gen_random_uuid(),
  name text unique not null,
  seat_capacity int not null,
  layout text not null check(layout in('2+2','2+1')),
  km_per_litre numeric(6,2) not null,
  ac_type text default 'Full AC',
  model_3d_url text
);

create table if not exists buses(
  id uuid primary key default gen_random_uuid(),
  model_id uuid references bus_models(id),
  registration_no text unique not null,
  display_name text not null,
  photo_url text,
  active boolean default true
);

create table if not exists routes(
  id uuid primary key default gen_random_uuid(),
  name text not null,
  origin text not null,
  destination text not null,
  distance_km numeric(8,2) not null,
  duration_minutes int not null,
  polyline text,
  active boolean default true,
  unique(origin,destination)
);

create table if not exists route_stops(
  id uuid primary key default gen_random_uuid(),
  route_id uuid references routes(id) on delete cascade,
  stop_name text not null,
  stop_order int not null,
  latitude numeric(10,7),
  longitude numeric(10,7),
  distance_from_origin_km numeric(8,2) default 0,
  unique(route_id,stop_order)
);

create table if not exists schedules(
  id uuid primary key default gen_random_uuid(),
  route_id uuid references routes(id),
  bus_id uuid references buses(id),
  driver_id uuid references drivers(id),
  departure_time timestamptz not null,
  arrival_time timestamptz not null,
  fare numeric(10,2) not null,
  active boolean default true,
  check(arrival_time > departure_time),
  unique(route_id, departure_time)
);

create table if not exists trips(
  id uuid primary key default gen_random_uuid(),
  schedule_id uuid unique references schedules(id),
  status trip_status default 'scheduled',
  started_at timestamptz,
  ended_at timestamptz,
  delay_minutes int default 0,
  delay_reason text,
  passenger_count int default 0,
  breakdown_notes text,
  last_location_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists seats(
  id uuid primary key default gen_random_uuid(),
  bus_id uuid references buses(id) on delete cascade,
  seat_no text not null,
  row_no int,
  column_no int,
  seat_type text default 'normal',
  unique(bus_id, seat_no),
  check (seat_type in ('normal','female','blocked'))
);

create table if not exists bookings(
  id uuid primary key default gen_random_uuid(),
  booking_code text unique default('SB-'||upper(substr(replace(gen_random_uuid()::text,'-',''),1,8))),
  user_id uuid references users(id),
  schedule_id uuid references schedules(id),
  origin_stop_id uuid references route_stops(id),
  destination_stop_id uuid references route_stops(id),
  origin_label text,
  destination_label text,
  status booking_status default 'pending',
  total_amount numeric(10,2) not null,
  created_at timestamptz default now()
);

create table if not exists booking_seats(
  id uuid primary key default gen_random_uuid(),
  booking_id uuid references bookings(id) on delete cascade,
  seat_id uuid references seats(id),
  status text default 'sold' check(status in('pending','sold')),
  unique(booking_id, seat_id)
);

create table if not exists payments(
  id uuid primary key default gen_random_uuid(),
  booking_id uuid unique references bookings(id),
  amount numeric(10,2) not null,
  status text default 'pending',
  test_reference text,
  paid_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists fuel_prices(
  price_date date unique not null,
  price_per_litre numeric(10,2) not null
);

create table if not exists fuel_logs(
  id uuid primary key default gen_random_uuid(),
  trip_id uuid references trips(id),
  litres numeric(10,2),
  cost numeric(10,2),
  logged_at timestamptz default now()
);

create table if not exists maintenance_logs(
  id uuid primary key default gen_random_uuid(),
  bus_id uuid references buses(id),
  title text,
  details text,
  starts_at timestamptz,
  ends_at timestamptz,
  completed boolean default false,
  cost numeric(10,2) default 0
);

create table if not exists gps_logs(
  id uuid primary key default gen_random_uuid(),
  trip_id uuid references trips(id) on delete cascade,
  latitude numeric(10,7),
  longitude numeric(10,7),
  speed numeric(7,2) default 0,
  heading numeric(6,2) default 0,
  recorded_at timestamptz default now()
);

create table if not exists notifications(
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  booking_id uuid references bookings(id),
  channel text default 'system',
  provider text,
  subject text,
  message text,
  status text default 'queued',
  error_message text,
  created_at timestamptz default now(),
  check(channel in ('email','system'))
);

create table if not exists audit_logs(
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id),
  action text not null,
  entity_type text,
  entity_id uuid,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- =========================================================
-- INDEXES
-- =========================================================

create index if not exists idx_schedule_search on schedules(route_id, departure_time);
create index if not exists idx_gps_latest on gps_logs(trip_id, recorded_at desc);
create index if not exists idx_booking_user on bookings(user_id, created_at desc);
create index if not exists idx_booking_schedule on bookings(schedule_id);
create index if not exists idx_route_stops_route on route_stops(route_id, stop_order);
create index if not exists idx_notifications_created_at on notifications(created_at desc);

-- =========================================================
-- SEATS AUTO CREATION TRIGGER (FIXED - NO AMBIGUITY)
-- =========================================================

create or replace function create_bus_seats()
returns trigger language plpgsql as $$
declare 
  cap int; 
  bus_layout text; 
  cols int; 
  i int;
begin
  select seat_capacity, layout into cap, bus_layout 
  from bus_models where id = new.model_id;
  
  cols := case when bus_layout = '2+1' then 3 else 4 end;

  for i in 1..cap loop
    insert into seats(bus_id, seat_no, row_no, column_no)
    values(new.id, i::text, ceil(i::numeric/cols), ((i-1)%cols)+1)
    on conflict do nothing;
  end loop;

  return new;
end $$;

drop trigger if exists buses_create_seats on buses;
create trigger buses_create_seats
after insert on buses
for each row execute function create_bus_seats();

-- =========================================================
-- SAFE ROUTE DISTANCE RECALC (FIXED - NO INFINITE RECURSION)
-- =========================================================

create or replace function recalc_stop_distances(p_route_id uuid)
returns void language plpgsql as $$
declare r record; o_lat numeric; o_lng numeric;
begin
  select latitude, longitude into o_lat, o_lng
  from route_stops
  where route_id=p_route_id
  order by stop_order limit 1;

  if o_lat is null then return; end if;

  for r in select id, latitude, longitude from route_stops where route_id=p_route_id loop
    update route_stops
    set distance_from_origin_km = round(
      (6371 * acos(least(1, greatest(-1,
        cos(radians(o_lat)) * cos(radians(r.latitude)) *
        cos(radians(r.longitude) - radians(o_lng)) +
        sin(radians(o_lat)) * sin(radians(r.latitude))
      ))))::numeric, 2)
    where id=r.id;
  end loop;
end $$;

-- Remove the old trigger that causes infinite recursion
drop trigger if exists route_stops_recalc_distance on route_stops;

-- Instead of a trigger, we'll create a function that can be called manually
-- or we'll use a different approach to avoid recursion

-- =========================================================
-- FARE CALCULATION
-- =========================================================

create or replace function fare_for_stops(
  p_schedule_id uuid,
  p_origin_stop uuid,
  p_destination_stop uuid
) returns numeric language plpgsql as $$
declare v_fare numeric; v_total numeric; v_from numeric; v_to numeric;
begin
  select fare into v_fare from schedules where id=p_schedule_id;
  select distance_km into v_total from routes r join schedules s on s.route_id=r.id where s.id=p_schedule_id;

  select distance_from_origin_km into v_from from route_stops where id=p_origin_stop;
  select distance_from_origin_km into v_to from route_stops where id=p_destination_stop;

  if v_total is null or v_from is null or v_to is null or v_to<=v_from then
    return v_fare;
  end if;

  return round(v_fare * ((v_to - v_from) / v_total), 2);
end $$;

-- =========================================================
-- TRIP AUTO CREATION
-- =========================================================

create or replace function create_trip_for_schedule()
returns trigger language plpgsql as $$
begin
  insert into trips(schedule_id, status)
  values(new.id, 'scheduled')
  on conflict(schedule_id) do nothing;
  return new;
end $$;

drop trigger if exists schedules_create_trip on schedules;

create trigger schedules_create_trip
after insert on schedules
for each row execute function create_trip_for_schedule();

-- =========================================================
-- VIEWS (SAFE RECREATE)
-- =========================================================

drop view if exists bus_allocation_conflicts cascade;
drop view if exists bus_allocations_view cascade;

create view bus_allocations_view as
select
  sc.id as schedule_id,
  b.id as bus_id,
  b.display_name,
  b.registration_no,
  r.origin,
  r.destination,
  u.full_name as driver_name,
  sc.departure_time,
  sc.arrival_time,
  t.status as trip_status
from schedules sc
left join buses b on b.id=sc.bus_id
left join routes r on r.id=sc.route_id
left join drivers d on d.id=sc.driver_id
left join users u on u.id=d.user_id
left join trips t on t.schedule_id=sc.id;

create view bus_allocation_conflicts as
select bus_id, display_name, registration_no, departure_time, count(*) as conflicts
from bus_allocations_view
group by bus_id, display_name, registration_no, departure_time
having count(*)>1;

-- =========================================================
-- SEED DATA (SAFE UPSERT STYLE)
-- =========================================================

insert into users(id,full_name,email,phone,password_hash,role)
values
('00000000-0000-0000-0000-000000000001','System Admin','admin@smartbus.lk','0770000001','dev:SmartBus123!','admin'),
('00000000-0000-0000-0000-000000000003','Customer User','customer@smartbus.lk','0770000003','dev:SmartBus123!','customer'),
-- ---- 10 driver logins (all password: SmartBus123!) ------------------------
('00000000-0000-0000-0000-000000000101','Tony stark','driver1@smartbus.lk','0771100001','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000102','peter parker','driver2@smartbus.lk','0771100002','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000103','bruce banner','driver3@smartbus.lk','0771100003','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000104','john wick','driver4@smartbus.lk','0771100004','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000105','thurai singam','driver5@smartbus.lk','0771100005','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000106','ben tennison','driver6@smartbus.lk','0771100006','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000107','arvinthan keerthanan','driver7@smartbus.lk','0771100007','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000108','thevarasa makilan','driver8@smartbus.lk','0771100008','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000109','steve harrington','driver9@smartbus.lk','0771100009','dev:SmartBus123!','driver'),
('00000000-0000-0000-0000-000000000110','steve rogers','driver10@smartbus.lk','0771100010','dev:SmartBus123!','driver')
on conflict(id) do update set full_name=excluded.full_name;

-- ---- 10 driver records, linked to the users above --------------------------
insert into drivers(id,user_id,license_no,license_expiry)
values
('00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000101','B1000001','2030-12-31'),
('00000000-0000-0000-0000-000000000202','00000000-0000-0000-0000-000000000102','B1000002','2030-12-31'),
('00000000-0000-0000-0000-000000000203','00000000-0000-0000-0000-000000000103','B1000003','2030-12-31'),
('00000000-0000-0000-0000-000000000204','00000000-0000-0000-0000-000000000104','B1000004','2030-12-31'),
('00000000-0000-0000-0000-000000000205','00000000-0000-0000-0000-000000000105','B1000005','2030-12-31'),
('00000000-0000-0000-0000-000000000206','00000000-0000-0000-0000-000000000106','B1000006','2030-12-31'),
('00000000-0000-0000-0000-000000000207','00000000-0000-0000-0000-000000000107','B1000007','2030-12-31'),
('00000000-0000-0000-0000-000000000208','00000000-0000-0000-0000-000000000108','B1000008','2030-12-31'),
('00000000-0000-0000-0000-000000000209','00000000-0000-0000-0000-000000000109','B1000009','2030-12-31'),
('00000000-0000-0000-0000-000000000210','00000000-0000-0000-0000-000000000110','B1000010','2030-12-31')
on conflict(id) do update set license_no=excluded.license_no;

-- ---- 3 bus models -----------------------------------------------------------
-- ---- patch older tables (created before ac_type / model_3d_url existed) ---
alter table bus_models add column if not exists ac_type text default 'Full AC';
alter table bus_models add column if not exists model_3d_url text;

insert into bus_models(id,name,seat_capacity,layout,km_per_litre,ac_type)
values
('00000000-0000-0000-0000-000000000301','Luxury AC Coach',40,'2+1',4.5,'Full AC'),
('00000000-0000-0000-0000-000000000302','Semi-Luxury Coach',49,'2+2',5.2,'Semi AC'),
('00000000-0000-0000-0000-000000000303','Super Express Coach',36,'2+1',4.0,'Full AC')
on conflict(name) do update set seat_capacity=excluded.seat_capacity;

-- ---- 10 buses across the 3 models -------------------------------------------
insert into buses(id,model_id,registration_no,display_name)
values
('00000000-0000-0000-0000-000000000401','00000000-0000-0000-0000-000000000301','NC-4581','Purple Express'),
('00000000-0000-0000-0000-000000000402','00000000-0000-0000-0000-000000000301','NC-4582','Northern Star'),
('00000000-0000-0000-0000-000000000403','00000000-0000-0000-0000-000000000302','NB-2210','City Comfort'),
('00000000-0000-0000-0000-000000000404','00000000-0000-0000-0000-000000000302','NB-2211','City Comfort II'),
('00000000-0000-0000-0000-000000000405','00000000-0000-0000-0000-000000000303','NA-7734','Super Rider'),
('00000000-0000-0000-0000-000000000406','00000000-0000-0000-0000-000000000303','NA-7735','Super Rider II'),
('00000000-0000-0000-0000-000000000407','00000000-0000-0000-0000-000000000301','NC-4590','Jaffna Queen'),
('00000000-0000-0000-0000-000000000408','00000000-0000-0000-0000-000000000302','NB-2299','Kandy Flyer'),
('00000000-0000-0000-0000-000000000409','00000000-0000-0000-0000-000000000303','NA-7799','Colombo Express'),
('00000000-0000-0000-0000-000000000410','00000000-0000-0000-0000-000000000301','NC-4600','Golden Arrow')
on conflict(registration_no) do update set display_name=excluded.display_name;
-- (inserting into buses fires buses_create_seats, which auto-generates every bus's seat map)

-- ---- 4 routes: Jaffna <-> Colombo, Jaffna <-> Kandy -------------------------
insert into routes(id,name,origin,destination,distance_km,duration_minutes)
values
('00000000-0000-0000-0000-000000000501','Northern Express','Jaffna','Colombo',396,420),
('00000000-0000-0000-0000-000000000502','Northern Return','Colombo','Jaffna',396,420),
('00000000-0000-0000-0000-000000000503','Hill Country','Jaffna','Kandy',300,360),
('00000000-0000-0000-0000-000000000504','Hill Country Return','Kandy','Jaffna',300,360)
on conflict(origin,destination) do update set distance_km=excluded.distance_km;

-- ---- stops per route (also drives the Google Map polyline/markers) ---------
insert into route_stops(route_id,stop_name,stop_order,latitude,longitude) values
('00000000-0000-0000-0000-000000000501','Jaffna',1,9.6615,80.0255),
('00000000-0000-0000-0000-000000000501','Vavuniya',2,8.7542,80.4982),
('00000000-0000-0000-0000-000000000501','Kurunegala',3,7.4863,80.3623),
('00000000-0000-0000-0000-000000000501','Colombo',4,6.9271,79.8612),
('00000000-0000-0000-0000-000000000502','Colombo',1,6.9271,79.8612),
('00000000-0000-0000-0000-000000000502','Kurunegala',2,7.4863,80.3623),
('00000000-0000-0000-0000-000000000502','Vavuniya',3,8.7542,80.4982),
('00000000-0000-0000-0000-000000000502','Jaffna',4,9.6615,80.0255),
('00000000-0000-0000-0000-000000000503','Jaffna',1,9.6615,80.0255),
('00000000-0000-0000-0000-000000000503','Vavuniya',2,8.7542,80.4982),
('00000000-0000-0000-0000-000000000503','Dambulla',3,7.8731,80.6511),
('00000000-0000-0000-0000-000000000503','Kandy',4,7.2906,80.6337),
('00000000-0000-0000-0000-000000000504','Kandy',1,7.2906,80.6337),
('00000000-0000-0000-0000-000000000504','Dambulla',2,7.8731,80.6511),
('00000000-0000-0000-0000-000000000504','Vavuniya',3,8.7542,80.4982),
('00000000-0000-0000-0000-000000000504','Jaffna',4,9.6615,80.0255)
on conflict(route_id,stop_order) do update set stop_name=excluded.stop_name;

-- Manually recalculate distances for all routes after inserting stops
select recalc_stop_distances(id) from routes;

-- ---- sample daily schedule (morning+night on the Colombo legs, night only --
-- ---- on the Kandy legs) — this is only a STARTING sample; add/edit/delete --
-- ---- more from the admin "Schedules" module exactly as needed -------------
insert into schedules(route_id,bus_id,driver_id,departure_time,arrival_time,fare) values
('00000000-0000-0000-0000-000000000501','00000000-0000-0000-0000-000000000401','00000000-0000-0000-0000-000000000201', (current_date+1)+time '06:00', (current_date+1)+time '13:00', 2800),
('00000000-0000-0000-0000-000000000502','00000000-0000-0000-0000-000000000402','00000000-0000-0000-0000-000000000202', (current_date+1)+time '06:30', (current_date+1)+time '13:30', 2800),
('00000000-0000-0000-0000-000000000501','00000000-0000-0000-0000-000000000403','00000000-0000-0000-0000-000000000203', (current_date+1)+time '20:00', (current_date+2)+time '03:00', 2800),
('00000000-0000-0000-0000-000000000502','00000000-0000-0000-0000-000000000404','00000000-0000-0000-0000-000000000204', (current_date+1)+time '20:30', (current_date+2)+time '03:30', 2800),
('00000000-0000-0000-0000-000000000503','00000000-0000-0000-0000-000000000405','00000000-0000-0000-0000-000000000205', (current_date+1)+time '21:00', (current_date+2)+time '03:00', 2200),
('00000000-0000-0000-0000-000000000504','00000000-0000-0000-0000-000000000406','00000000-0000-0000-0000-000000000206', (current_date+1)+time '21:30', (current_date+2)+time '03:30', 2200),
('00000000-0000-0000-0000-000000000501','00000000-0000-0000-0000-000000000407','00000000-0000-0000-0000-000000000207', (current_date+1)+time '07:00', (current_date+1)+time '14:00', 2800),
('00000000-0000-0000-0000-000000000502','00000000-0000-0000-0000-000000000408','00000000-0000-0000-0000-000000000208', (current_date+1)+time '07:30', (current_date+1)+time '14:30', 2800)
on conflict(route_id,departure_time) do nothing;
-- (inserting into schedules fires schedules_create_trip, which auto-creates each trip row)

-- =========================================================
-- RLS SAFE ENABLE
-- =========================================================

do $$
begin
  begin alter table users enable row level security; exception when others then null; end;
  begin alter table bookings enable row level security; exception when others then null; end;
  begin alter table gps_logs enable row level security; exception when others then null; end;
end $$;

-- =========================================================
-- END
-- =========================================================