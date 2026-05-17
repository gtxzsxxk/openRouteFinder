export interface Airport {
  icao: string
  name: string
  lat: number
  lon: number
  runways?: string[]
}

export interface Waypoint {
  name: string
  lat: number
  lon: number
}

export interface RunwayThreshold {
  name: string
  lat: number
  lon: number
  heading: number
}

export interface Runway {
  name: string
  thresholds: RunwayThreshold[]
  length: number
  width: number
}

// SID/STAR procedure from backend: [name, runway, points, transitions]
// transitions: [[transName, transPoints], ...]
export type ProcedureTuple = [string, string, [string, number, number][], [string, [string, number, number][]][]]

export type SID = Record<string, ProcedureTuple[]>
export type STAR = Record<string, ProcedureTuple[]>

export interface RouteNode extends Waypoint {}

export interface RouteResult {
  data_version: string
  total_time: string
  route: string
  distance: string
  nodes: RouteNode[]
  SID: SID
  STAR: STAR
  airportName: string[]
  weather: [string, string]
  origRunways?: Runway[]
  destRunways?: Runway[]
  activeSIDTransition?: string
  activeSTARTransition?: string
}

export interface ValidCode {
  token: string
  image: string
}

export interface Metar {
  icao: string
  metar: string
}

export interface ProcedureOption {
  name: string
  procedures: string[]
}

export interface AirportProcedureResponse {
  icao: string
  sid: {
    exits: ProcedureOption[]
  }
  star: {
    entries: ProcedureOption[]
  }
}
